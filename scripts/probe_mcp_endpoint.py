"""Network-only MCP handshake probe. No credentials and no tools/call."""
import json
import urllib.request
import urllib.error

body={'jsonrpc':'2.0','id':1,'method':'initialize','params':{
    'protocolVersion':'2025-11-25','capabilities':{},
    'clientInfo':{'name':'vericomedia-runner-reachability','version':'0.1.0'}}}
request=urllib.request.Request('https://tilda.ru/api/mcp/',data=json.dumps(body).encode(),
    headers={'Content-Type':'application/json','Accept':'application/json, text/event-stream'})
try:
    with urllib.request.urlopen(request,timeout=30) as response:status=response.status
except urllib.error.HTTPError as error:status=error.code
except urllib.error.URLError:
    print(json.dumps({'endpoint_reachable':False,'authentication_verified':False}))
    raise SystemExit(1)
print(json.dumps({'http_status':status,'authentication_verified':False,'tools_called':False}))
if status>=500:raise SystemExit('MCP endpoint temporarily unhealthy')
