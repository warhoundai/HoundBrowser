/** Run in a trusted Node.js backend. Forward only the scoped viewer grant to a UI. */
import {HoundBrowser} from '../sdk/js/client.mjs';
const browser=new HoundBrowser({endpoint:process.env.HOUNDBROWSER_URL||'http://127.0.0.1:8080',apiKey:process.env.HOUNDBROWSER_API_KEY});
const id=process.env.HOUNDBROWSER_SESSION_ID;if(!id)throw Error('Set HOUNDBROWSER_SESSION_ID to a session owned by this key');
const grant=await browser.viewer(id,{frames:false});const url=new URL(grant.path,browser.endpoint);url.protocol=url.protocol==='https:'?'wss:':'ws:';
const socket=new WebSocket(url,['houndbrowser','ticket.'+grant.ticket]);socket.addEventListener('message',event=>console.log(JSON.parse(event.data)));socket.addEventListener('open',()=>console.log('Read-only event stream connected'));
