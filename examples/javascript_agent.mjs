import {HoundBrowser} from '../sdk/js/client.mjs';
const browser=new HoundBrowser({endpoint:process.env.HOUNDBROWSER_URL||'http://127.0.0.1:8080',apiKey:process.env.HOUNDBROWSER_API_KEY});
const session=await browser.create('https://example.com');try{const result=await browser.run(session.id,'navigate',{url:'https://example.com'});console.log(result);}finally{await browser.close(session.id);}
