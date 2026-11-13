"""One process, one tenant/session. Browser children inherit no AWS credentials."""
import asyncio
import base64
import hashlib
import json
import os
import time
import uuid
from urllib.parse import urlsplit
from playwright.async_api import async_playwright
from .network import PublicProxy,PublicNetworkError,origin
from .contracts import ProtocolError,require,check_url,redact

class Browser:
    def __init__(self,scope,emit,proxy=None,clock=time.monotonic):
        self.scope,self.emit,self.proxy,self.clock=scope,emit,proxy or PublicProxy(),clock
        self.revision=0;self.pages={};self.page=None;self.elements={};self.events=[];self.secrets=[];self.touched=clock();self.lock=asyncio.Lock();self.epoch=0;self.experiments=set();self.journal={};self.network_lock=asyncio.Lock();self.next_request=0;self.pending_network=0
    async def start(self):
        self.playwright=await async_playwright().start();proxy=await self.proxy.start()
        self.browser=await self.playwright.chromium.launch(headless=True,**({'executable_path':os.environ['BROWSER_EXECUTABLE']} if os.environ.get('BROWSER_EXECUTABLE') else {}),proxy={'server':proxy},env={k:os.environ[k] for k in ['PATH','HOME','TMPDIR','LANG','LC_ALL','TZ'] if k in os.environ},args=['--disable-dev-shm-usage','--disable-quic','--proxy-bypass-list=<-loopback>','--force-webrtc-ip-handling-policy=disable_non_proxied_udp'])
        self.proxy_url=proxy
        self.context=await self.browser.new_context(viewport={'width':1280,'height':720},accept_downloads=False,service_workers='block',permissions=[])
        self.context.set_default_timeout(8000);self.context.set_default_navigation_timeout(20000)
        await self.context.route('**/*',self.route)
        await self.context.route_web_socket('**/*',self.websocket_route)
        self.context.on('page',self.track_page)
        self.page=await self.context.new_page()
    async def reserve_network(self):
        require(self.pending_network<32,429,'NETWORK_BACKPRESSURE','Browser network backpressure reached')
        self.pending_network+=1
        try:
            async with self.network_lock:
                now=self.clock();delay=max(0,self.next_request-now);self.next_request=max(now,self.next_request)+0.1
            if delay:await asyncio.sleep(delay)
        finally:self.pending_network-=1
    async def route(self,route):
        try:
            # All resource requests share the same public-only exact-origin network policy.
            check_url(self.scope,route.request.url,route.request.method)
            require(len(route.request.post_data_buffer or b'')<=16384,413)
            await self.reserve_network()
            await route.continue_()
        except (ProtocolError,ValueError):
            self.events.append({'kind':'policy_block','method':route.request.method,'url':self.safe_url(route.request.url)})
            await route.abort()
    async def websocket_route(self,route):
        try:
            value=route.url.replace('wss://','https://',1).replace('ws://','http://',1)
            check_url(self.scope,value)
            require(self.scope['websockets'],403)
            route.connect_to_server()
        except (ProtocolError,ValueError):await route.close()
    def track_page(self,page):
        if page not in self.pages.values():self.pages[uuid.uuid4().hex]=page
        page.on('console',lambda message:self.events.append({'kind':'console','type':message.type,'text':self.clean(message.text)}))
        page.on('response',lambda response:self.events.append({'kind':'response','url':self.safe_url(response.url),'status':response.status}))
        page.on('framenavigated',lambda frame:self.navigation(frame,page))
    def navigation(self,frame,page):
        if frame==page.main_frame:self.revision+=1;self.elements={}
    @staticmethod
    def safe_url(value):
        u=urlsplit(value);return u.scheme+'://'+u.netloc+u.path if u.scheme in ('http','https') else 'about:blank'
    def clean(self,value):
        value=redact(value)
        if isinstance(value,str):
            for secret in self.secrets:
                if secret:value=value.replace(secret,'[REDACTED]')
        elif isinstance(value,dict):value={k:self.clean(v) for k,v in value.items()}
        elif isinstance(value,list):value=[self.clean(v) for v in value]
        return value
    async def observe(self):
        self.secrets=list(set(self.secrets+[c['value'] for c in await self.context.cookies() if c['value']]))
        self.revision+=1;self.elements={}
        handles=await self.page.query_selector_all('a,button,input,textarea,select,[role="button"],[contenteditable="true"]')
        items=[]
        for handle in handles[:200]:
            data=await handle.evaluate("""e=>({tag:e.tagName.toLowerCase(),type:e.type||'',label:(e.getAttribute('aria-label')||e.innerText||e.placeholder||e.name||'').slice(0,120),visible:!!e.getClientRects().length,sensitive:e.type==='password'||/password|one-time-code|cc-/.test(e.autocomplete||'')})""")
            if not data['visible'] or data['sensitive']:continue
            eid=str(self.revision)+'-'+str(len(items));self.elements[eid]=handle
            items.append({'id':eid,'role':data['tag'],'label':data['label']})
        text=await self.page.evaluate("document.body?.innerText?.slice(0,12000)||''")
        return self.clean({'url':self.safe_url(self.page.url),'title':await self.page.title(),'text':text,'elements':items,'revision':self.revision})
    async def screenshot(self):
        import re
        masks=[self.page.locator('input,textarea,[contenteditable="true"],[data-sensitive]')]+[self.page.get_by_text(re.compile(re.escape(v))) for v in self.secrets if len(v)>=8]
        return await self.page.screenshot(type='jpeg',quality=55,mask=masks,timeout=5000)
    async def authenticate(self,profile):
        require(self.scope.get('credentialProfile'),403)
        require(set(profile)<= {'url','username','password','usernameSelector','passwordSelector','submitSelector','successSelector'},400)
        check_url(self.scope,profile['url']);self.secrets=[profile['username'],profile['password']]
        # These selectors come from operator-managed configuration, never a model command.
        await self.page.goto(profile['url']);await self.page.locator(profile['usernameSelector']).fill(profile['username']);await self.page.locator(profile['passwordSelector']).fill(profile['password']);await self.page.locator(profile['submitSelector']).click();await self.page.locator(profile['successSelector']).wait_for(state='visible');self.revision+=1
    async def execute(self,command,epoch):
        cid=command['id']
        if cid in self.journal:return self.journal[cid]
        async with self.lock:
            self.touched=self.clock();self.journal[cid]={'status':'running'}
            try:
                require(command['revision']==self.revision,409,'STALE_PAGE','The page changed; observe its current revision')
                require(epoch==self.epoch,409,'STALE_LEASE','Command was cancelled')
                result=await asyncio.wait_for(self.action(command['action'],command.get('args',{})),130)
                value={'status':'completed','result':self.clean(result),'revision':self.revision}
            except asyncio.CancelledError:
                self.journal[cid]={'status':'cancelled','revision':self.revision};raise
            except ProtocolError as e:value={'status':'failed','result':{'code':e.code,'message':str(e)},'revision':self.revision}
            except asyncio.TimeoutError:
                await self.context.close();value={'status':'outcome_unknown','result':{'code':'ACTION_TIMEOUT','message':'Browser closed after timeout; do not replay state-changing actions'},'revision':self.revision}
            except Exception:value={'status':'outcome_unknown','result':{'code':'PAGE_CHANGED','message':'The action outcome could not be established; do not replay a state-changing action'},'revision':self.revision}
            self.journal[cid]=value;return value
    async def action(self,name,args):
        if name=='navigate':
            check_url(self.scope,args['url']);await self.page.goto(args['url'],wait_until='domcontentloaded');return await self.observe()
        if name=='observe':return await self.observe()
        if name in ('click','type','select'):
            handle=self.elements.get(args.get('elementId'));require(handle,409,'STALE_ELEMENT','Observe before interacting')
            sensitive=await handle.evaluate("e=>e.type==='password'||/password|one-time-code|cc-/.test(e.autocomplete||'')")
            require(not sensitive,403,'SENSITIVE_CONTROL','Use the credential-profile mechanism for sensitive fields')
            if name=='click':await handle.click()
            elif name=='type':require(isinstance(args.get('text'),str) and len(args['text'])<=2000);await handle.fill(args['text'])
            else:await handle.select_option(args['value'])
            return await self.observe()
        if name=='scroll':await self.page.mouse.wheel(0,max(-2000,min(2000,int(args.get('pixels',600)))));return await self.observe()
        if name=='key':
            require(args.get('key') in ['Enter','Tab','Escape','ArrowDown','ArrowUp','ArrowLeft','ArrowRight','Space','Backspace']);await self.page.keyboard.press(args['key']);return await self.observe()
        if name in ('back','forward'):
            await (self.page.go_back() if name=='back' else self.page.go_forward());return await self.observe()
        if name=='tabs':return {'tabs':[{'id':k,'url':self.safe_url(p.url)} for k,p in self.pages.items() if not p.is_closed()]}
        if name=='new_tab':
            require(sum(not p.is_closed() for p in self.pages.values())<8,429,'TAB_CAPACITY','Close a tab before opening another');self.page=await self.context.new_page();return await self.observe()
        if name=='switch_tab':
            target=self.pages.get(args.get('tabId'));require(target and not target.is_closed(),404);self.page=target;await target.bring_to_front();return await self.observe()
        if name=='close_tab':
            target=self.pages.get(args.get('tabId'));require(target,404);await target.close();remaining=[p for p in self.pages.values() if not p.is_closed()];self.page=remaining[0] if remaining else await self.context.new_page();return await self.observe()
        if name=='screenshot':
            data=await self.screenshot();return {'image':{'mimeType':'image/jpeg','data':base64.b64encode(data).decode()},'sha256':hashlib.sha256(data).hexdigest(),'revision':self.revision}
        if name=='diagnostics':self.events=self.events[-200:];return {'events':self.clean(self.events),'coverage':'Observed traffic and policy blocks only'}
        if name=='http':return await self.http(args)
        if name=='evaluate':
            require(not self.scope.get('credentialProfile'),403,'AUTHENTICATED_JS_BLOCKED','Use constrained assertions with authenticated sessions')
            require(isinstance(args.get('script'),str) and len(args['script'])<=10000)
            result=await self.page.evaluate(args['script']);require(len(json.dumps(result).encode())<=12000,413);self.revision+=1;self.elements={};return {'value':result,'revision':self.revision}
        if name=='assert':
            # No model-provided JavaScript or selectors run in authenticated contexts.
            kind=args.get('check');require(kind in ('text_present','element_count','url_path','response_status'))
            if kind=='text_present':return {'matched':str(args.get('text','')) in (await self.page.inner_text('body')),'revision':self.revision}
            if kind=='element_count':return {'count':len(self.elements),'revision':self.revision}
            if kind=='url_path':return {'path':urlsplit(self.page.url).path,'revision':self.revision}
            return {'statuses':[e['status'] for e in self.events if e['kind']=='response'][-30:],'revision':self.revision}
        if name in ('rate_test','alias_test'):return await self.experiment(name,args)
        raise ProtocolError(400,'UNKNOWN_ACTION','Unsupported action')
    async def http(self,args):
        url=args['url'];method=args.get('method','GET').upper();check_url(self.scope,url,method);await self.reserve_network()
        # Only synthetic write paths accept request bodies; no model-supplied credentials or headers.
        body=args.get('body');require(body is None or method not in ('GET','HEAD'));require(body is None or isinstance(body,str) and len(body)<=12000)
        import httpx
        headers={}
        cookies=await self.context.cookies(url)
        if cookies:headers['cookie']='; '.join(c['name']+'='+c['value'] for c in cookies)
        if body is not None:headers['content-type']='application/json'
        if not getattr(self,'http_client',None):
            self.http_client=httpx.AsyncClient(proxy=self.proxy_url,follow_redirects=False,timeout=8,trust_env=False)
        # The browser context remains the only cookie authority, including deletions.
        self.http_client.cookies.clear()
        started=self.clock()
        async with self.http_client.stream(method,url,content=body,headers=headers) as response:
            data=bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk);require(len(data)<=262144,413,'RESPONSE_TOO_LARGE','Response body exceeded evidence limit')
            milliseconds=int((self.clock()-started)*1000)
            selected={k:v for k,v in response.headers.items() if k.lower() in ('content-type','retry-after','ratelimit-limit','ratelimit-remaining','ratelimit-reset','x-ratelimit-remaining')}
            return self.clean({'url':self.safe_url(url),'status':response.status_code,'headers':selected,'body':bytes(data[:12000]).decode('utf8','replace'),'bytes':len(data),'truncated':len(data)>12000,'sha256':hashlib.sha256(data).hexdigest(),'milliseconds':milliseconds})
    async def experiment(self,name,args):
        experiment=args.get('experimentId');require(isinstance(experiment,str) and experiment and experiment not in self.experiments,409,'EXPERIMENT_USED','Use a new authorized experiment identifier')
        target=args['url'];check_url(self.scope,target,args.get('method','GET').upper());require(urlsplit(target).path.startswith('/__houndbrowser_test__/'),403,'SYNTHETIC_ONLY','Experiments require synthetic fixture endpoints')
        count=args.get('requests',20);require(type(count) is int and 1<=count<=60)
        self.experiments.add(experiment);rows=[]
        if name=='alias_test':
            require(self.scope.get('credentialProfile') is None,403)
            require(args.get('mailSink')=='fixture',403,'MAIL_SINK_REQUIRED','Alias tests require an operator-controlled fixture mail sink')
            base='wh-'+uuid.uuid4().hex[:12];bodies=[json.dumps({'email':base+suffix+'@mail.invalid','mailSink':'fixture'}) for suffix in ('','+one','+two')]
            require(args.get('method')=='POST',400);count=min(count,len(bodies))
        phases=(['alias']*count if name=='alias_test' else (['baseline']*min(3,count)+['paced']*min(6,max(0,count-3))+['burst']*max(0,count-12)+['recovery']*min(3,max(0,count-9))))
        for index,phase in enumerate(phases):
            if index:await asyncio.sleep(1 if phase in ('baseline','recovery') else 0.5)
            started=self.clock();r=await self.http({**args,**({'body':bodies[index]} if name=='alias_test' else {})});latency=r['milliseconds'];rows.append({'request':index+1,'phase':phase,'status':r['status'],'milliseconds':latency,'headers':r['headers'],'bodyHash':r['sha256']})
            if r['status']==429 or r['status']>=500 or latency>3000:break
        return {'requests':rows,'coverage':'Bounded synthetic experiment; successful responses alone do not establish a vulnerability','verification':'Observed','stoppedEarly':len(rows)<count}
    async def close(self):
        if getattr(self,'http_client',None):await self.http_client.aclose()
        if hasattr(self,'context'):await self.context.close()
        if hasattr(self,'browser'):await self.browser.close()
        if hasattr(self,'playwright'):await self.playwright.stop()
        await self.proxy.close()
