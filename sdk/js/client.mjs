/** Backend service client. Never put the API key into a browser application or prompt. */
export class HoundBrowserError extends Error{constructor(status,value){super(value.error||'Browser request failed');this.status=status;this.code=value.code;}}
export class HoundBrowser{
 constructor({endpoint,apiKey,fetcher=fetch}){const u=new URL(endpoint);if(u.username||u.password||u.search||u.hash||u.pathname!=='/'||u.protocol!=='https:'&&!(u.protocol==='http:'&&['localhost','127.0.0.1','[::1]'].includes(u.hostname)))throw Error('HTTPS or loopback HTTP required');this.endpoint=u.origin;this.apiKey=apiKey;this.fetcher=fetcher;}
 async request(method,path,value){const r=await this.fetcher(this.endpoint+'/v1/browser'+path,{method,headers:{authorization:'Bearer '+this.apiKey,'content-type':'application/json'},...(value===undefined?{}:{body:JSON.stringify(value)}),redirect:'error',signal:AbortSignal.timeout(30000)});const data=await r.json();if(!r.ok)throw new HoundBrowserError(r.status,data);return data;}
 create(origin,scope={}){return this.request('POST','/sessions',{scope:{...scope,origin}});}
 session(id){return this.request('GET','/sessions/'+encodeURIComponent(id));}
 async submit(id,{action,args={},revision,commandId=crypto.randomUUID()}){if(revision===undefined)revision=(await this.session(id)).revision;return this.request('POST','/sessions/'+encodeURIComponent(id)+'/commands',{id:commandId,idempotencyKey:commandId,action,args,revision});}
 command(id,cid){return this.request('GET','/sessions/'+encodeURIComponent(id)+'/commands/'+encodeURIComponent(cid));}
 async run(id,action,args={},options={}){const accepted=await this.submit(id,{action,args,...options});const until=Date.now()+(options.timeoutMs||150000);while(Date.now()<until){const result=await this.command(id,accepted.id);if(['completed','failed','cancelled','outcome_unknown'].includes(result.status))return result;await new Promise(r=>setTimeout(r,150));}throw Error('Query the original command ID before retrying an uncertain action');}
 close(id){return this.request('DELETE','/sessions/'+encodeURIComponent(id));}
 cancel(id){return this.request('POST','/sessions/'+encodeURIComponent(id)+'/cancel',{});}
 viewer(id,{frames=true}={}){return this.request('POST','/sessions/'+encodeURIComponent(id)+'/viewer',{frames});}
 async artifact(id,sha){if(!/^[a-f0-9]{64}$/.test(sha))throw Error('Invalid artifact digest');const r=await this.fetcher(this.endpoint+'/v1/browser/sessions/'+encodeURIComponent(id)+'/artifacts/'+sha,{headers:{authorization:'Bearer '+this.apiKey},redirect:'error',signal:AbortSignal.timeout(30000)});if(!r.ok)throw Error('Artifact unavailable');const bytes=new Uint8Array(await r.arrayBuffer());const hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(v=>v.toString(16).padStart(2,'0')).join('');if(hash!==sha)throw Error('Artifact integrity mismatch');return bytes;}
}
