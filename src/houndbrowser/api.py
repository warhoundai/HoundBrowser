"""Single-node reference service. No model providers or application integrations."""
import asyncio
import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response
from .browser import Browser
from .contracts import ProtocolError, require, scope_manifest, command_body, canonical, digest, identifier, ACTIONS
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

class SessionScope(BaseModel):
    model_config=ConfigDict(extra="forbid")
    origin:str
    methods:list[Literal["GET","HEAD","POST","PUT","PATCH","DELETE"]]=["GET","HEAD"]
    writePaths:list[str]=[]
    credentialProfile:str|None=None
    websockets:bool=False

class SessionInput(BaseModel):
    model_config=ConfigDict(extra="forbid")
    scope:SessionScope

class CommandInput(BaseModel):
    model_config=ConfigDict(extra="forbid")
    id:str=Field(min_length=1,max_length=100,pattern=r"^[a-zA-Z0-9_-]+$")
    idempotencyKey:str=Field(min_length=1,max_length=100,pattern=r"^[a-zA-Z0-9_-]+$")
    action:Literal[tuple(sorted(ACTIONS))]
    args:dict=Field(default_factory=dict)
    revision:int=Field(ge=0,strict=True)
    agent:str="primary"


class Registry:
    def __init__(self, path):
        self.db=sqlite3.connect(path,check_same_thread=False,isolation_level=None)
        self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA busy_timeout=5000')
        self.db.executescript('CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, tenant TEXT NOT NULL, state TEXT NOT NULL, scope TEXT NOT NULL, active TEXT NOT NULL DEFAULT \'\', created REAL NOT NULL); CREATE TABLE IF NOT EXISTS commands(session TEXT NOT NULL,id TEXT NOT NULL, fingerprint TEXT NOT NULL,status TEXT NOT NULL,value TEXT NOT NULL,PRIMARY KEY(session,id)); CREATE TABLE IF NOT EXISTS events(cursor INTEGER PRIMARY KEY AUTOINCREMENT,session TEXT NOT NULL,value TEXT NOT NULL); CREATE INDEX IF NOT EXISTS session_events ON events(session,cursor); CREATE TABLE IF NOT EXISTS artifacts(session TEXT NOT NULL,id TEXT NOT NULL,value BLOB NOT NULL,PRIMARY KEY(session,id));')
        self.db.execute("UPDATE commands SET status='outcome_unknown' WHERE status IN ('accepted','running')")
        self.db.execute("UPDATE sessions SET state='closed',active='' WHERE state!='closed'")
    def get(self,sid,tenant):
        row=self.db.execute('SELECT id,tenant,state,scope,active,created FROM sessions WHERE id=? AND tenant=?',(sid,tenant)).fetchone()
        require(row,404,'NOT_FOUND','Session not found');return dict(zip(['id','tenant','state','scope','active','created'],row))
    def event(self,sid,value):
        cursor=self.db.execute('INSERT INTO events(session,value) VALUES(?,?)',(sid,canonical(value))).lastrowid
        self.db.execute('DELETE FROM events WHERE session=? AND cursor < ?',(sid,cursor-1000));return {'eventId':str(cursor),**value}
    def claim(self,sid,tenant,cmd):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row=self.get(sid,tenant);require(row['state']=='ready',409,'NOT_READY','Session is not ready')
            old=self.db.execute('SELECT fingerprint,status,value FROM commands WHERE session=? AND id=?',(sid,cmd['id'])).fetchone()
            if old:
                require(old[0]==digest(cmd),409,'IDEMPOTENCY_CONFLICT','Command ID has different content')
                self.db.execute('COMMIT');return False
            require(not row['active'],409,'BUSY','A command already holds this session lease')
            self.db.execute('INSERT INTO commands VALUES(?,?,?,?,?)',(sid,cmd['id'],digest(cmd),'accepted',canonical(cmd)))
            self.db.execute('UPDATE sessions SET active=? WHERE id=?',(cmd['id'],sid));self.db.execute('COMMIT');return True
        except Exception:self.db.execute('ROLLBACK');raise

class Settings:
    def __init__(self, *, keys=None, origins=None, database=None, maximum=8, profiles=None):
        self.keys=keys if keys is not None else json.loads(os.environ.get('HOUNDBROWSER_API_KEYS','{}'))
        require(self.keys and all(isinstance(k,str) and isinstance(v,str) and len(v)>=32 for k,v in self.keys.items()),500,'CONFIGURATION','Configure tenant API keys with at least 32 characters')
        self.origins=origins if origins is not None else json.loads(os.environ.get('HOUNDBROWSER_ALLOWED_ORIGINS','[]'))
        require(isinstance(self.origins,list) and self.origins,500,'CONFIGURATION','Configure approved HTTPS origins')
        self.database=database or os.environ.get('HOUNDBROWSER_DATABASE','houndbrowser.sqlite3')
        self.maximum=maximum;self.profiles=profiles or {};self.tickets={}
    def tenant(self,authorization):
        token=authorization.removeprefix('Bearer ') if authorization.startswith('Bearer ') else ''
        wanted=hashlib.sha256(token.encode()).digest();found=None
        for tenant,key in self.keys.items():
            if hmac.compare_digest(wanted,hashlib.sha256(key.encode()).digest()):found=tenant
        require(found is not None,401,'UNAUTHORIZED','A valid service API key is required');return found

def create_app(settings=None,browser_factory=Browser):
    config=settings or Settings();registry=Registry(config.database);sessions={};jobs={};streams={};epoch={};monitors={};frames={}
    def own(sid,tenant,live=True):
        row=registry.get(sid,tenant)
        if live:require(row['state']=='ready' and sid in sessions,410,'CLOSED','Session is closed')
        return row
    async def emit(sid,value):
        value=registry.event(sid,value)
        for q in streams.get(sid,set()).copy():
            if q.full():
                try:q.get_nowait()
                except asyncio.QueueEmpty:pass
            q.put_nowait(value)
    async def close(sid,tenant):
        row=own(sid,tenant,False)
        if row['state']=='closed':return
        epoch[sid]=epoch.get(sid,0)+1
        if sid in monitors:monitors[sid].cancel();await asyncio.gather(monitors.pop(sid),return_exceptions=True)
        if sid in jobs:jobs[sid].cancel();await asyncio.gather(jobs[sid],return_exceptions=True)
        if sid in sessions:await sessions.pop(sid).close()
        frames.pop(sid,None)
        registry.db.execute("UPDATE sessions SET state='closed',active='' WHERE id=?",(sid,))
        registry.db.execute("UPDATE commands SET status='outcome_unknown' WHERE session=? AND status IN ('accepted','running')",(sid,))
        await emit(sid,{'type':'closed'})
    async def observe_changes(sid,browser):
        prior=''
        while sid in sessions:
            await asyncio.sleep(1)
            if browser.lock.locked():continue
            try:
                observation=None
                async with browser.lock:
                    fingerprint=await browser.page.evaluate("document.body?.innerHTML?.slice(0,100000)||''")
                    if fingerprint!=prior:
                        prior=fingerprint;observation=await browser.observe()
                if observation:await emit(sid,{'type':'observation','data':observation})
            except asyncio.CancelledError:raise
            except Exception:continue
    async def reaper():
        while True:
            await asyncio.sleep(10)
            for sid,browser in list(sessions.items()):
                if browser and sid not in jobs and browser.clock()-browser.touched>300:
                    row=registry.db.execute('SELECT tenant FROM sessions WHERE id=?',(sid,)).fetchone()
                    if row:await close(sid,row[0])
            now=time.time();config.tickets={k:v for k,v in config.tickets.items() if v['expires']>now}
    @asynccontextmanager
    async def lifespan(app):
        task=asyncio.create_task(reaper())
        try:yield
        finally:
            task.cancel();await asyncio.gather(task,return_exceptions=True)
            for sid in list(sessions):
                row=registry.db.execute('SELECT tenant FROM sessions WHERE id=?',(sid,)).fetchone()
                await close(sid,row[0])
            registry.db.close()
    app=FastAPI(title='HoundBrowser API',version='0.1.0',lifespan=lifespan,docs_url=None,redoc_url=None)
    app.state.registry=registry;app.state.sessions=sessions
    @app.exception_handler(ProtocolError)
    async def protocol_error(request,error):return JSONResponse({'error':str(error),'code':error.code},status_code=error.status)
    @app.middleware('http')
    async def boundary(request,call_next):
        try:
            if request.url.path!='/health':request.state.tenant=config.tenant(request.headers.get('authorization',''))
            raw=bytearray()
            async for chunk in request.stream():
                raw.extend(chunk);require(len(raw)<=20000,413,'BODY_TOO_LARGE','Request exceeds 20 KB')
            request._body=bytes(raw)
            response=await call_next(request);response.headers['Cache-Control']='no-store';response.headers['X-Content-Type-Options']='nosniff';return response
        except ProtocolError as e:return JSONResponse({'error':str(e),'code':e.code},status_code=e.status)
        except (ValueError,TypeError):return JSONResponse({'error':'Invalid request','code':'INVALID_REQUEST'},status_code=400)
    @app.get('/health')
    async def health():return {'status':'ok','version':'0.1.0'}
    @app.post('/v1/browser/sessions',status_code=201)
    async def create(request:Request,value:SessionInput):
        scope=scope_manifest(value.scope.model_dump(exclude_none=True),config.origins)
        profile=scope.get('credentialProfile')
        if profile:require(profile in config.profiles and config.profiles[profile]['origin']==scope['origin'],403,'PROFILE_SCOPE','Profile is not approved for this origin')
        require(len(sessions)<config.maximum,429,'CAPACITY','Browser capacity reached')
        sid=uuid.uuid4().hex;tenant=request.state.tenant
        # Reserve before the first await, preventing concurrent creates from over-admitting.
        sessions[sid]=None
        browser=browser_factory(scope,lambda event:emit(sid,event))
        try:
            await browser.start()
            if profile:await browser.authenticate(config.profiles[profile]['credentials'])
            sessions[sid]=browser;epoch[sid]=0
            if hasattr(browser,'page'):monitors[sid]=asyncio.create_task(observe_changes(sid,browser))
            registry.db.execute('INSERT INTO sessions(id,tenant,state,scope,created) VALUES(?,?,?,?,?)',(sid,tenant,'ready',canonical(scope),time.time()))
            return {'id':sid,'state':'ready','scope':scope,'revision':browser.revision}
        except Exception:
            sessions.pop(sid,None);await browser.close();raise ProtocolError(503,'START_FAILED','Browser could not start')
    @app.get('/v1/browser/sessions/{sid}')
    async def status(sid:str,request:Request):
        row=own(sid,request.state.tenant,False);return {'id':sid,'state':row['state'],'revision':sessions[sid].revision if sid in sessions and sessions[sid] else None,'scope':json.loads(row['scope'])}
    async def execute(sid,cmd):
        try:
            registry.db.execute("UPDATE commands SET status='running' WHERE session=? AND id=?",(sid,cmd['id']))
            result=await sessions[sid].execute(cmd,epoch[sid]);image=result.get('result',{}).pop('image',None)
            if image:
                data=base64.b64decode(image['data']);require(len(data)<=2000000,413,'EVIDENCE_TOO_LARGE','Evidence exceeds limit')
                sha=hashlib.sha256(data).hexdigest();registry.db.execute('INSERT OR IGNORE INTO artifacts VALUES(?,?,?)',(sid,sha,data))
                result['result']['artifact']={'artifactId':sha,'sha256':sha,'bytes':len(data),'mimeType':'image/jpeg'}
            result['id']=cmd['id'];result['action']=cmd['action']
            registry.db.execute('UPDATE commands SET status=?,value=? WHERE session=? AND id=?',(result['status'],canonical(result),sid,cmd['id']))
            await emit(sid,{'type':'command_status',**result})
        except asyncio.CancelledError:raise
        except Exception:
            result={'id':cmd['id'],'status':'outcome_unknown','result':{'code':'WORKER_ERROR','message':'Inspect state before replaying an action'}}
            registry.db.execute("UPDATE commands SET status='outcome_unknown',value=? WHERE session=? AND id=?",(canonical(result),sid,cmd['id']))
        finally:
            registry.db.execute("UPDATE sessions SET active='' WHERE id=?",(sid,));jobs.pop(sid,None)
    @app.post('/v1/browser/sessions/{sid}/commands',status_code=202)
    async def submit(sid:str,request:Request,value:CommandInput):
        row=own(sid,request.state.tenant);cmd=command_body(value.model_dump(),bool(json.loads(row['scope']).get('credentialProfile')))
        require(cmd['idempotencyKey']==cmd['id'],400,'IDEMPOTENCY_KEY','Use the command ID as its idempotency key')
        if registry.claim(sid,request.state.tenant,cmd):jobs[sid]=asyncio.create_task(execute(sid,cmd))
        return command_value(sid,cmd['id'])
    def command_value(sid,cid):
        record=registry.db.execute('SELECT status,value FROM commands WHERE session=? AND id=?',(sid,cid)).fetchone();require(record,404,'NOT_FOUND','Command not found')
        value=json.loads(record[1]);return {**value,'status':record[0]}
    @app.get('/v1/browser/sessions/{sid}/commands/{cid}')
    async def command(sid:str,cid:str,request:Request):own(sid,request.state.tenant,False);return command_value(sid,cid)
    @app.delete('/v1/browser/sessions/{sid}')
    async def delete(sid:str,request:Request):await close(sid,request.state.tenant);return {'closed':True}
    @app.post('/v1/browser/sessions/{sid}/cancel')
    async def cancel(sid:str,request:Request):
        own(sid,request.state.tenant);epoch[sid]+=1;sessions[sid].epoch=epoch[sid]
        if sid in jobs:jobs[sid].cancel();await asyncio.gather(jobs[sid],return_exceptions=True)
        registry.db.execute("UPDATE commands SET status='outcome_unknown' WHERE session=? AND status IN ('accepted','running')",(sid,));return {'cancelled':True,'epoch':epoch[sid]}
    @app.get('/v1/browser/sessions/{sid}/events')
    async def events(sid:str,request:Request,after:int=0):
        own(sid,request.state.tenant,False)
        rows=registry.db.execute('SELECT cursor,value FROM events WHERE session=? AND cursor>? ORDER BY cursor LIMIT 200',(sid,after))
        return {'events':[{'eventId':str(i),**json.loads(v)} for i,v in rows]}
    @app.get('/v1/browser/sessions/{sid}/artifacts/{sha}')
    async def artifact(sid:str,sha:str,request:Request):
        own(sid,request.state.tenant,False);row=registry.db.execute('SELECT value FROM artifacts WHERE session=? AND id=?',(sid,sha)).fetchone();require(row,404,'NOT_FOUND','Artifact not found')
        return Response(row[0],media_type='image/jpeg',headers={'ETag':'"'+sha+'"','X-Content-SHA256':sha})
    @app.post('/v1/browser/sessions/{sid}/viewer')
    async def viewer(sid:str,request:Request):
        own(sid,request.state.tenant);ticket=secrets.token_urlsafe(32);frames=(await request.json()).get('frames',True) is True
        config.tickets[ticket]={'sid':sid,'tenant':request.state.tenant,'expires':time.time()+60,'frames':frames}
        return {'path':'/v1/browser/live','ticket':ticket,'expiresIn':60}
    @app.websocket('/v1/browser/live')
    async def live(ws:WebSocket):
        protocols=[v.strip() for v in ws.headers.get('sec-websocket-protocol','').split(',')];ticket=next((v[7:] for v in protocols if v.startswith('ticket.')),'');grant=config.tickets.pop(ticket,None)
        if not grant or grant['expires']<=time.time():await ws.close(code=4401);return
        sid=grant['sid']
        try:own(sid,grant['tenant'])
        except ProtocolError:await ws.close(code=4403);return
        if len(streams.get(sid,set()))>=10:await ws.close(code=4429);return
        await ws.accept(subprotocol='houndbrowser');q=asyncio.Queue(maxsize=4);streams.setdefault(sid,set()).add(q)
        async def receive():
            while True:
                message=await ws.receive_text()
                if message!='ping':await ws.close(code=4403);return
        receiver=asyncio.create_task(receive());next_frame=0
        try:
            while not receiver.done() and sid in sessions:
                try:
                    event=await asyncio.wait_for(q.get(),0.5);await ws.send_json(event)
                except asyncio.TimeoutError:pass
                if grant['frames'] and sid in sessions and time.monotonic()>=next_frame:
                    browser=sessions[sid];next_frame=time.monotonic()+0.5
                    if not browser.lock.locked():
                        async with browser.lock:
                            prior=frames.get(sid)
                            if not prior or time.monotonic()-prior[0]>=0.5:
                                data=await browser.screenshot();frames[sid]=(time.monotonic(),data,prior[2]+1 if prior else 1)
                            _,data,sequence=frames[sid]
                        await ws.send_json({'type':'frame','sequence':sequence,'mimeType':'image/jpeg','data':base64.b64encode(data).decode()})
        except (WebSocketDisconnect,RuntimeError):pass
        finally:receiver.cancel();await asyncio.gather(receiver,return_exceptions=True);streams.get(sid,set()).discard(q)
    original_schema=app.openapi
    def schema():
        value=original_schema();value.setdefault('components',{}).setdefault('securitySchemes',{})['serviceKey']={'type':'http','scheme':'bearer'}
        for path,methods in value['paths'].items():
            for operation in methods.values():operation['security']=[] if path=='/health' else [{'serviceKey':[]}]
        return value
    app.openapi=schema
    return app
