"""Run against the package's own container. Prints no keys or target page contents."""
import base64,hashlib,json,os,pathlib,secrets,socket,struct,subprocess,tempfile,time,urllib.request,urllib.error,uuid
image=os.environ.get('HOUNDBROWSER_SMOKE_IMAGE','houndbrowser:test');key=secrets.token_urlsafe(32);name='houndbrowser-smoke-'+uuid.uuid4().hex[:8]
with tempfile.TemporaryDirectory() as folder:
    env=pathlib.Path(folder)/'runtime.env';env.write_text('HOUNDBROWSER_API_KEYS='+json.dumps({'smoke':key})+'\nHOUNDBROWSER_ALLOWED_ORIGINS=["https://ops.warhoundai.com"]\n');env.chmod(0o600)
    subprocess.run(['docker','run','--detach','--init','--name',name,'--shm-size=1g','--tmpfs','/data:uid=10001,gid=10001,mode=700','-p','127.0.0.1:18080:8080','--env-file',str(env),image],check=True,stdout=subprocess.DEVNULL)
    def request(method,path,value=None,authorized=True):
        req=urllib.request.Request('http://127.0.0.1:18080'+path,data=json.dumps(value).encode() if value is not None else None,headers={'content-type':'application/json',**({'authorization':'Bearer '+key} if authorized else {})},method=method)
        with urllib.request.urlopen(req,timeout=150) as r:return r.status,r.read()
    sid=None
    try:
        for _ in range(60):
            try:
                status,body=request('GET','/health');assert status==200;break
            except (OSError,urllib.error.URLError):time.sleep(1)
        else:raise RuntimeError('Container did not become healthy')
        try:request('GET','/v1/browser/sessions/missing',authorized=False);raise AssertionError('Anonymous API request allowed')
        except urllib.error.HTTPError as e:assert e.code==401
        status,body=request('POST','/v1/browser/sessions',{'scope':{'origin':'https://ops.warhoundai.com'}});assert status==201;session=json.loads(body);sid=session['id']
        def run(action,args):
            _,body=request('GET','/v1/browser/sessions/'+sid);revision=json.loads(body)['revision'];cid=uuid.uuid4().hex
            _,body=request('POST','/v1/browser/sessions/'+sid+'/commands',{'id':cid,'idempotencyKey':cid,'action':action,'args':args,'revision':revision})
            for _ in range(300):
                _,body=request('GET','/v1/browser/sessions/'+sid+'/commands/'+cid);result=json.loads(body)
                if result['status'] not in ('accepted','running'):
                    if result['status']=='failed' and result.get('result',{}).get('code')=='STALE_PAGE':return run(action,args)
                    assert result['status']=='completed',result.get('result',{}).get('code');return result['result']
                time.sleep(.5)
            raise TimeoutError('Command did not complete')
        result=run('navigate',{'url':'https://ops.warhoundai.com'});assert 'WarHound' in result['title']
        screenshot=run('screenshot',{});artifact=screenshot['artifact'];_,data=request('GET','/v1/browser/sessions/'+sid+'/artifacts/'+artifact['artifactId']);assert hashlib.sha256(data).hexdigest()==artifact['sha256']
        _,grant_body=request('POST','/v1/browser/sessions/'+sid+'/viewer',{'frames':True});grant=json.loads(grant_body)
        with socket.create_connection(('127.0.0.1',18080),timeout=20) as stream:
            nonce=base64.b64encode(secrets.token_bytes(16)).decode()
            upgrade=('GET '+grant['path']+' HTTP/1.1\r\nHost: 127.0.0.1:18080\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: '+nonce+'\r\nSec-WebSocket-Protocol: houndbrowser, ticket.'+grant['ticket']+'\r\n\r\n').encode()
            stream.sendall(upgrade);buffer=bytearray()
            while b'\r\n\r\n' not in buffer:buffer.extend(stream.recv(4096))
            header,remaining=bytes(buffer).split(b'\r\n\r\n',1);assert header.split(b'\r\n',1)[0].startswith(b'HTTP/1.1 101')
            pending=bytearray(remaining)
            def read_exact(n):
                while len(pending)<n:
                    part=stream.recv(max(4096,n-len(pending)))
                    if not part:raise RuntimeError('WebSocket closed before a frame')
                    pending.extend(part)
                value=bytes(pending[:n]);del pending[:n];return value
            saw_frame=False
            for _ in range(10):
                first,second=read_exact(2);length=second&127
                if length==126:length=struct.unpack('!H',read_exact(2))[0]
                elif length==127:length=struct.unpack('!Q',read_exact(8))[0]
                assert length<3000000
                message=read_exact(length)
                if first&15==1:
                    event=json.loads(message)
                    if event.get('type')=='frame':assert len(base64.b64decode(event['data']))>100;saw_frame=True;break
            assert saw_frame
        request('DELETE','/v1/browser/sessions/'+sid);sid=None
        uid=subprocess.check_output(['docker','exec',name,'id','-u'],text=True).strip();assert uid=='10001'
        print(json.dumps({'containerSmokePassed':True,'anonymousRequestsDenied':True,'realChromiumNavigation':True,'liveWebSocketFrames':True,'evidenceIntegrity':True,'sessionClosed':True,'nonRootUid':int(uid)}))
    finally:
        if sid:
            try:request('DELETE','/v1/browser/sessions/'+sid)
            except Exception:pass
        subprocess.run(['docker','rm','--force',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
