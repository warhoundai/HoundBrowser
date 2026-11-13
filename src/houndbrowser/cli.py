import argparse
import os

def main():
    parser=argparse.ArgumentParser(prog='houndbrowser');parser.add_argument('command',choices=['serve']);parser.add_argument('--host',default='127.0.0.1');parser.add_argument('--port',type=int,default=8080);args=parser.parse_args()
    import uvicorn
    from .api import create_app
    # One process owns its browser sessions. Never silently launch multiple ASGI workers.
    uvicorn.run(create_app(),host=args.host,port=args.port,workers=1,proxy_headers=False,access_log=False)
