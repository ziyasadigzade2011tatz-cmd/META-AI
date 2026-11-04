"""Opt-in MCP Streamable HTTP client for explicitly configured local servers."""
import json,os,re,uuid,time
from urllib.parse import urlsplit
import httpx

def validate_server(name,server):
 if not re.fullmatch('[A-Za-z0-9_-]{1,40}',name) or not isinstance(server,dict) or set(server)-{'url','tools','token_env'}:raise ValueError('Invalid MCP configuration')
 url=urlsplit(server.get('url',''))
 if url.scheme!='http' or url.hostname!='127.0.0.1' or url.username or url.password or not url.port or url.query or url.fragment:raise ValueError('MCP requires explicit http://127.0.0.1:port/path')
 allowed=server.get('tools',[])
 if not isinstance(allowed,list) or len(allowed)>30 or any(not re.fullmatch('[A-Za-z0-9_.-]{1,100}',n) for n in allowed):raise ValueError('Invalid MCP tool allowlist')
 if server.get('token_env') and not re.fullmatch('[A-Z][A-Z0-9_]{0,80}',server['token_env']):raise ValueError('Use an environment variable name, never a token')
 return server

class Client:
 def __init__(self,name,server):self.server=validate_server(name,server);self.session=None;self.client=httpx.Client(timeout=25,trust_env=False,follow_redirects=False);self.counter=0
 def rpc(self,method,params=None,notification=False):
  self.counter+=1;number=self.counter;payload={'jsonrpc':'2.0','method':method,'params':params or {}}
  if not notification:payload['id']=number
  headers={'Accept':'application/json, text/event-stream','MCP-Protocol-Version':'2025-03-26'}
  if self.session:headers['Mcp-Session-Id']=self.session
  if self.server.get('token_env'):
   token=os.environ.get(self.server['token_env'])
   if not token:raise ValueError('MCP credential environment variable missing')
   headers['Authorization']='Bearer '+token
  with self.client.stream('POST',self.server['url'],json=payload,headers=headers) as response:
   response.raise_for_status()
   if method=='initialize':self.session=response.headers.get('Mcp-Session-Id')
   raw=bytearray();started=time.monotonic()
   for chunk in response.iter_bytes():
    raw.extend(chunk)
    if len(raw)>2_000_000 or time.monotonic()-started>30:raise ValueError('MCP response budget exceeded')
    if 'text/event-stream' in response.headers.get('Content-Type','') and b'\n\n' in bytes(raw).replace(b'\r\n',b'\n'):
     for raw_frame in bytes(raw).replace(b'\r\n',b'\n').split(b'\n\n')[:-1]:
      frame=raw_frame.decode('utf-8')
      lines=[l[5:].lstrip() for l in frame.splitlines() if l.startswith('data:')]
      if not lines:continue
      value=json.loads('\n'.join(lines))
      if value.get('id')==number:
       if 'error' in value:raise ValueError('MCP server returned error')
       return value.get('result',{})
   if notification:return {}
   value=json.loads(raw)
   if value.get('id')!=number or 'error' in value:raise ValueError('MCP invalid RPC response')
   return value.get('result',{})
 def __enter__(self):
  try:
   self.rpc('initialize',{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'META','version':'1.0'}});self.rpc('notifications/initialized',notification=True);return self
  except BaseException:self.client.close();raise
 def __exit__(self,*args):self.client.close()
 def tools(self):return self.rpc('tools/list').get('tools',[])
 def call(self,name,args):
  if name not in self.server.get('tools',[]):raise PermissionError('MCP tool not allowlisted')
  return self.rpc('tools/call',{'name':name,'arguments':args})
