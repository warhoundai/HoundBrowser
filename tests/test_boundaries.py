import pytest,time,concurrent.futures,asyncio
from fastapi.testclient import TestClient
from houndbrowser.network import public_url,origin,PublicNetworkError
from houndbrowser.contracts import scope_manifest,check_url,command_body,ProtocolError
from test_api import settings,FakeBrowser,headers,create,command
from houndbrowser.api import create_app

# Reserved example credentials are intentionally rejected by the boundary.
@pytest.mark.parametrize('url',['http://127.0.0.1','https://169.254.169.254','https://[::1]','https://10.0.0.1','https://192.168.1.1','https://localhost','https://internal.local','file:///etc/passwd','https://user:password@example.com','https://example.com:8443']) # pragma: allowlist secret
def test_private_network_and_non_web_destinations_are_blocked(url):
    with pytest.raises((PublicNetworkError,ValueError)):public_url(url)

@pytest.mark.parametrize('url,method',[('https://other.example','GET'),('https://example.com/write','POST'),('http://example.com','GET'),('https://example.com:8443','GET')])
def test_scope_never_expands_from_target_data(url,method):
    scope=scope_manifest({'origin':'https://example.com'},['https://example.com'])
    with pytest.raises(ProtocolError):check_url(scope,url,method)

def test_write_path_is_explicit_and_authenticated_js_denied():
    scope=scope_manifest({'origin':'https://example.com','methods':['GET','POST'],'writePaths':['/own-fixture']},['https://example.com'])
    assert check_url(scope,'https://example.com/own-fixture','POST')
    with pytest.raises(ProtocolError):check_url(scope,'https://example.com/elsewhere','POST')
    with pytest.raises(ProtocolError):command_body({**command(),'action':'evaluate'},authenticated=True)
    with pytest.raises(ProtocolError):command_body({**command(),'revision':True})

def test_concurrent_api_requests_get_one_command_lease():
    class Slow(FakeBrowser):
        async def execute(self,cmd,epoch):await asyncio.sleep(.3);return await super().execute(cmd,epoch)
    with TestClient(create_app(settings(),Slow)) as c:
        sid=create(c)
        def submit(i):return c.post(f'/v1/browser/sessions/{sid}/commands',headers=headers(),json=command('c'+str(i))).status_code
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:statuses=list(pool.map(submit,range(4)))
        assert statuses.count(202)==1;assert statuses.count(409)==3

def test_cancellation_revokes_epoch_and_records_uncertain_outcome():
    class Slow(FakeBrowser):
        async def execute(self,cmd,epoch):await asyncio.sleep(10);return await super().execute(cmd,epoch)
    with TestClient(create_app(settings(),Slow)) as c:
        sid=create(c);path=f'/v1/browser/sessions/{sid}'
        assert c.post(path+'/commands',headers=headers(),json=command()).status_code==202
        assert c.post(path+'/cancel',headers=headers(),json={}).json()['epoch']==1
        assert c.get(path+'/commands/test',headers=headers()).json()['status']=='outcome_unknown'

def test_schema_describes_authentication_and_command_actions():
    with TestClient(create_app(settings(),FakeBrowser)) as c:
        schema=c.get('/openapi.json',headers=headers()).json()
        assert schema['components']['securitySchemes']['serviceKey']['scheme']=='bearer'
        assert schema['paths']['/health']['get']['security']==[]
        assert schema['components']['schemas']['CommandInput']['properties']['action']['enum']
