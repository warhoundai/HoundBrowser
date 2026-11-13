"""Synchronous service client. API keys never enter browser arguments."""
import hashlib
import time
import uuid
from urllib.parse import urlsplit
import httpx

class APIError(RuntimeError):
    def __init__(self,status,value):super().__init__(value.get('error','HoundBrowser request failed'));self.status=status;self.code=value.get('code')
class Client:
    def __init__(self,endpoint,*,api_key,timeout=30,transport=None):
        u=urlsplit(endpoint)
        if u.username or u.password or u.query or u.fragment or u.path not in ('','/') or u.scheme!='https' and not(u.scheme=='http' and u.hostname in ('127.0.0.1','localhost','::1')):raise ValueError('Use HTTPS, or loopback HTTP for local development')
        self.http=httpx.Client(base_url=endpoint.rstrip('/'),headers={'authorization':'Bearer '+api_key},timeout=timeout,follow_redirects=False,transport=transport)
    def __enter__(self):return self
    def __exit__(self,*_):self.http.close()
    def request(self,method,path,value=None):
        r=self.http.request(method,path,**({'json':value} if value is not None else {}))
        if not r.is_success:
            try:value=r.json()
            except ValueError:value={'error':'Service returned an invalid response'}
            raise APIError(r.status_code,value)
        return r.json()
    def create(self,origin,**scope):return self.request('POST','/v1/browser/sessions',{'scope':{'origin':origin,**scope}})
    def session(self,sid):return self.request('GET','/v1/browser/sessions/'+sid)
    def submit(self,sid,action,args=None,*,command_id=None,revision=None):
        cid=command_id or uuid.uuid4().hex
        if revision is None:revision=self.session(sid)['revision']
        return self.request('POST',f'/v1/browser/sessions/{sid}/commands',{'id':cid,'idempotencyKey':cid,'action':action,'args':args or {},'revision':revision})
    def command(self,sid,cid):return self.request('GET',f'/v1/browser/sessions/{sid}/commands/{cid}')
    def run(self,sid,action,args=None,*,command_id=None,timeout=150):
        accepted=self.submit(sid,action,args,command_id=command_id);deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            result=self.command(sid,accepted['id'])
            if result['status'] in ('completed','failed','cancelled','outcome_unknown'):return result
            time.sleep(.15)
        raise TimeoutError('Query the original command ID; do not resubmit an uncertain action')
    def close(self,sid):return self.request('DELETE',f'/v1/browser/sessions/{sid}')
    def cancel(self,sid):return self.request('POST',f'/v1/browser/sessions/{sid}/cancel',{})
    def viewer(self,sid,*,frames=True):return self.request('POST',f'/v1/browser/sessions/{sid}/viewer',{'frames':frames})
    def artifact(self,sid,sha):
        r=self.http.get(f'/v1/browser/sessions/{sid}/artifacts/{sha}')
        if not r.is_success:raise APIError(r.status_code,{'error':'Artifact unavailable'})
        if hashlib.sha256(r.content).hexdigest()!=sha:raise ValueError('Artifact integrity check failed')
        return r.content
