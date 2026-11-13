"""Versioned browser protocol. Target data is never authorization."""
import hashlib
import json
import re
from urllib.parse import urlsplit
from .network import public_url, origin

ACTIONS = {'navigate','observe','click','type','select','scroll','key','back','forward','tabs','new_tab','switch_tab','close_tab','screenshot','diagnostics','http','evaluate','assert','rate_test','alias_test'}
MUTATIONS = ACTIONS - {'observe','tabs','screenshot','diagnostics'}
TERMINAL = {'completed','failed','cancelled','outcome_unknown'}
class ProtocolError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code = status, code
        super().__init__(message)

def require(condition, status=400, code='INVALID_REQUEST', message='Invalid browser request'):
    if not condition: raise ProtocolError(status,code,message)

def identifier(value):
    require(isinstance(value,str) and re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',value))
    return value

def canonical(value): return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)
def digest(value): return hashlib.sha256(canonical(value).encode()).hexdigest()

def scope_manifest(value, fixtures):
    require(isinstance(value,dict) and set(value)<= {'origin','methods','writePaths','credentialProfile','websockets'})
    try:
        target=origin(value['origin'])
        public_url(target)
    except (ValueError,KeyError): raise ProtocolError(400,'INVALID_SCOPE','A public HTTPS origin is required')
    require(target.startswith('https://') and target in fixtures,403,'ORIGIN_NOT_ALLOWED','Only operator-approved origins are available')
    methods=value.get('methods',['GET','HEAD'])
    require(isinstance(methods,list) and methods and set(methods)<= {'GET','HEAD','POST','PUT','PATCH','DELETE'})
    paths=value.get('writePaths',[])
    require(isinstance(paths,list) and all(isinstance(p,str) and p.startswith('/') and not p.startswith('//') and not any(c in p for c in ('%','?','#','..')) for p in paths))
    require(not(set(methods)-{'GET','HEAD'}) or paths,403,'WRITE_SCOPE_REQUIRED','Write methods need exact approved paths')
    profile=value.get('credentialProfile')
    if profile is not None: identifier(profile)
    return {'origin':target,'methods':sorted(set(methods)),'writePaths':sorted(set(paths)),'credentialProfile':profile,'websockets':value.get('websockets') is True}

def check_url(scope,url,method='GET'):
    try: public_url(url); u=urlsplit(url); same=origin(url)==scope['origin']
    except ValueError: raise ProtocolError(403,'OUT_OF_SCOPE','Destination is blocked')
    require(same and method in scope['methods'],403,'OUT_OF_SCOPE','Destination or method is outside scope')
    if method not in ('GET','HEAD'):
        require(u.path in scope['writePaths'],403,'OUT_OF_SCOPE','Write path is not explicitly authorized')
    return url

def command_body(value,authenticated=False):
    require(isinstance(value,dict) and set(value)<= {'id','idempotencyKey','action','args','revision','agent'})
    identifier(value.get('id')); identifier(value.get('idempotencyKey')); identifier(value.get('agent','primary'))
    require(value.get('action') in ACTIONS)
    require(isinstance(value.get('args',{}),dict) and len(canonical(value).encode())<=20000)
    require(type(value.get('revision')) is int and value['revision']>=0)
    require(not(authenticated and value['action']=='evaluate'),403,'AUTHENTICATED_JS_BLOCKED','Authenticated sessions support worker-owned assertions only')
    return {**value,'args':value.get('args',{}),'agent':value.get('agent','primary')}

def redact(value):
    if isinstance(value,dict):
        return {k:('[REDACTED]' if re.search(r'cookie|password|authorization|secret|token|storage',k,re.I) else redact(v)) for k,v in value.items()}
    if isinstance(value,list): return [redact(v) for v in value[:200]]
    if isinstance(value,str):
        value=re.sub(r'(?i)(bearer\s+|(?:password|secret|token|api[_-]?key)\s*[:=]\s*)[^\s,;]+',r'\1[REDACTED]',value)
        return value[:20000]
    return value
