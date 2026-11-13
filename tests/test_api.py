import asyncio,json,sqlite3,time,uuid
import pytest
from fastapi.testclient import TestClient
from houndbrowser.api import Registry,Settings,create_app
from houndbrowser.contracts import ProtocolError
KEY='a'*40;OTHER='b'*40
class FakeBrowser:
    def __init__(self,scope,emit):self.scope=scope;self.revision=0;self.epoch=0;self.clock=time.monotonic;self.touched=time.monotonic();self.closed=False;self.lock=asyncio.Lock()
    async def start(self):pass
    async def close(self):self.closed=True
    async def execute(self,cmd,epoch):
        await asyncio.sleep(.03);self.revision+=1
        return {'status':'completed','revision':self.revision,'result':{'title':'Controlled fixture','revision':self.revision}}
    async def screenshot(self):return b'controlled-frame'

def settings(path=':memory:',maximum=8):return Settings(keys={'owner':KEY,'other':OTHER},origins=['https://example.com'],database=path,maximum=maximum)
def headers(key=KEY):return {'authorization':'Bearer '+key}
def create(client):
    r=client.post('/v1/browser/sessions',headers=headers(),json={'scope':{'origin':'https://example.com'}});assert r.status_code==201,r.text;return r.json()['id']
def command(cid='test',action='navigate'):return {'id':cid,'idempotencyKey':cid,'action':action,'args':{'url':'https://example.com'},'revision':0}

def test_auth_scope_and_body_size_are_enforced():
    with TestClient(create_app(settings(),FakeBrowser)) as c:
        assert c.get('/health').status_code==200
        assert c.get('/openapi.json').status_code==401
        assert c.get('/openapi.json',headers=headers()).status_code==200
        assert c.post('/v1/browser/sessions',headers=headers(),json={'scope':{'origin':'https://127.0.0.1'}}).status_code==400
        assert c.post('/v1/browser/sessions',headers=headers(),json={'scope':{'origin':'https://elsewhere.example'}}).status_code==403
        assert c.post('/v1/browser/sessions',headers=headers(),content=b'x'*20001).status_code==413

def test_session_ownership_idempotency_and_capacity():
    with TestClient(create_app(settings(maximum=1),FakeBrowser)) as c:
        sid=create(c);path=f'/v1/browser/sessions/{sid}'
        assert c.get(path,headers=headers(OTHER)).status_code==404
        assert c.post('/v1/browser/sessions',headers=headers(),json={'scope':{'origin':'https://example.com'}}).status_code==429
        body=command();r=c.post(path+'/commands',headers=headers(),json=body);assert r.status_code==202,r.text
        assert c.post(path+'/commands',headers=headers(),json=body).status_code==202
        assert c.post(path+'/commands',headers=headers(),json=command(action='observe')).status_code==409
        for _ in range(30):
            r=c.get(path+'/commands/test',headers=headers()).json()
            if r['status']=='completed':break
            time.sleep(.02)
        assert r['status']=='completed'
        assert c.get(path+'/commands/test',headers=headers(OTHER)).status_code==404
        assert c.delete(path,headers=headers()).json()=={'closed':True}
        assert c.delete(path,headers=headers()).status_code==200
        assert c.get(path,headers=headers()).json()['state']=='closed'

def test_viewer_ticket_one_use_and_read_only():
    with TestClient(create_app(settings(),FakeBrowser)) as c:
        sid=create(c);grant=c.post(f'/v1/browser/sessions/{sid}/viewer',headers=headers(),json={'frames':False}).json()
        with c.websocket_connect(grant['path'],subprotocols=['houndbrowser','ticket.'+grant['ticket']]) as ws:
            ws.send_text('command');assert ws.receive()['type']=='websocket.close'
        with pytest.raises(Exception):
            with c.websocket_connect(grant['path'],subprotocols=['houndbrowser','ticket.'+grant['ticket']]):pass

def test_atomic_command_lease_and_restart_unknown(tmp_path):
    path=str(tmp_path/'status.sqlite3');db=Registry(path)
    db.db.execute('INSERT INTO sessions VALUES(?,?,?,?,?,?)',('s','owner','ready','{}','',time.time()))
    cmd=command();assert db.claim('s','owner',cmd)
    assert not db.claim('s','owner',cmd)
    with pytest.raises(ProtocolError):db.claim('s','owner',command('second'))
    db.db.close();after=Registry(path)
    assert after.db.execute('SELECT status FROM commands').fetchone()[0]=='outcome_unknown'
    assert after.get('s','owner')['state']=='closed';after.db.close()

def test_unconfigured_credentials_fail_closed():
    with pytest.raises(ProtocolError):Settings(keys={},origins=['https://example.com'])
    with pytest.raises(ProtocolError):Settings(keys={'owner':'short'},origins=['https://example.com'])

def test_viewer_uses_asgi_subprotocols_when_server_consumes_raw_header():
    app=create_app(settings(),FakeBrowser)
    async def consumed_header(scope,receive,send):
        if scope['type']=='websocket':
            scope={**scope,'headers':[(k,v) for k,v in scope['headers'] if k.lower()!=b'sec-websocket-protocol']}
        await app(scope,receive,send)
    with TestClient(consumed_header) as c:
        sid=create(c);grant=c.post(f'/v1/browser/sessions/{sid}/viewer',headers=headers(),json={'frames':False}).json()
        with c.websocket_connect(grant['path'],subprotocols=['houndbrowser','ticket.'+grant['ticket']]) as ws:
            ws.send_text('command');assert ws.receive()['code']==4403
