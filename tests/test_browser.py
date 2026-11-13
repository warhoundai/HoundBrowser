import asyncio,json,unittest
from houndbrowser.browser import Browser
from houndbrowser.contracts import ProtocolError
from houndbrowser.network import PublicProxy
class BrowserTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.hits=[]
        html=b'''<html><title>Owned fixture</title><body><h1>Fixture</h1><input name="note" aria-label="Note"><input type="password" value="sensitive"><button onclick="document.querySelector('h1').textContent='Changed'">Change</button></body></html>'''
        async def fixture(reader,writer):
            try:
                data=await reader.readuntil(b'\r\n\r\n');self.hits.append(data.split(b'\r\n')[0]);writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: '+str(len(html)).encode()+b'\r\nConnection: close\r\n\r\n'+html);await writer.drain()
            finally:writer.close()
        self.server=await asyncio.start_server(fixture,'127.0.0.1',0);self.port=self.server.sockets[0].getsockname()[1]
        async def resolver(host,port):
            if host!='example.com':raise ValueError('Not fixture')
            return ['93.184.216.34']
        async def connector(ip,port):return await asyncio.open_connection('127.0.0.1',self.port)
        self.browser=Browser({'origin':'http://example.com','methods':['GET','HEAD'],'writePaths':[],'credentialProfile':None,'websockets':False},lambda _:None,proxy=PublicProxy(resolver,connector));await self.browser.start()
    async def asyncTearDown(self):await self.browser.close();self.server.close();await self.server.wait_closed()
    async def test_real_chromium_observation_click_stale_handles_and_screenshot(self):
        observed=await self.browser.action('navigate',{'url':'http://example.com/'})
        self.assertEqual(observed['title'],'Owned fixture');self.assertNotIn('sensitive',json.dumps(observed))
        button=next(x for x in observed['elements'] if x['role']=='button')
        result=await self.browser.execute({'id':'one','action':'click','args':{'elementId':button['id']},'revision':observed['revision']},0)
        self.assertEqual(result['status'],'completed');self.assertIn('Changed',result['result']['text'])
        stale=await self.browser.execute({'id':'two','action':'click','args':{'elementId':button['id']},'revision':self.browser.revision},0)
        self.assertEqual(stale['status'],'failed')
        image=await self.browser.action('screenshot',{});self.assertEqual(image['image']['mimeType'],'image/jpeg')
    async def test_stale_revision_returns_terminal_failure_instead_of_losing_result(self):
        result=await self.browser.execute({'id':'stale','action':'evaluate','args':{'script':'document.title'},'revision':-1},0)
        self.assertEqual(result['status'],'failed');self.assertEqual(result['result']['code'],'STALE_PAGE')
        self.assertEqual(self.browser.journal['stale'],result)
    async def test_evaluate_and_http_real_fixture(self):
        await self.browser.action('navigate',{'url':'http://example.com/'})
        value=await self.browser.action('evaluate',{'script':'document.title'});self.assertEqual(value['value'],'Owned fixture')
        response=await self.browser.action('http',{'url':'http://example.com/'});self.assertEqual(response['status'],200);self.assertIn('Fixture',response['body'])
        adapter=self.browser.http_client
        repeated=await self.browser.action('http',{'url':'http://example.com/'})
        self.assertIs(self.browser.http_client,adapter);self.assertEqual(repeated['status'],200);self.assertGreaterEqual(repeated['milliseconds'],0)
        self.browser.scope['credentialProfile']='test-role'
        with self.assertRaises(ProtocolError):await self.browser.action('evaluate',{'script':'document.cookie'})
    async def test_out_of_scope_never_reaches_fixture(self):
        with self.assertRaises(ProtocolError):await self.browser.action('navigate',{'url':'http://127.0.0.1/'})
        self.assertEqual(self.hits,[])
    async def test_rate_observation_stops_and_never_fabricates(self):
        calls=[]
        async def request(args):calls.append(args);return {'status':429,'headers':{'retry-after':'60'},'sha256':'a'*64,'milliseconds':10}
        self.browser.http=request
        result=await self.browser.action('rate_test',{'url':'http://example.com/__houndbrowser_test__/rate','requests':60,'experimentId':'bounded'})
        self.assertEqual(len(calls),1);self.assertTrue(result['stoppedEarly']);self.assertEqual(result['verification'],'Observed')
        with self.assertRaises(ProtocolError):await self.browser.action('rate_test',{'url':'http://example.com/__houndbrowser_test__/rate','requests':61,'experimentId':'too-many'})

