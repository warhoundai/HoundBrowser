"""Read-only example. Configure the example origin in the service allowlist first."""
import os
from houndbrowser.client import Client
with Client(os.environ.get('HOUNDBROWSER_URL','http://127.0.0.1:8080'),api_key=os.environ['HOUNDBROWSER_API_KEY']) as browser:
    session=browser.create('https://example.com')
    try:
        result=browser.run(session['id'],'navigate',{'url':'https://example.com'})
        if result['status']!='completed':raise RuntimeError('Inspect the command result before deciding whether to retry')
        print(result['result']['title'])
    finally:browser.close(session['id'])
