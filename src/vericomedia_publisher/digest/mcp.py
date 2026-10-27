"""Minimal Streamable HTTP MCP client. Read retries only; writes never retried."""
import json
import os
import time
import urllib.request
import urllib.error
from .common import PipelineError, UnknownOutcome

READ_TOOLS = {'describe_tool','get_projects','get_pages','get_page_settings','get_project_settings',
              'get_page_records','edit_record','get_record_html','tpls_list'}
WRITE_TOOLS = {'add_blank_page','update_page_settings','add_record','update_record','publish_page'}

class MCP:
    endpoint = 'https://tilda.ru/api/mcp/'
    def __init__(self, writes=False, token=None):
        self.token = token or os.environ.get('TILDA_MCP_TOKEN')
        if not self.token: raise PipelineError('missing_TILDA_MCP_TOKEN')
        self.session = None; self.version = None; self.counter = 0; self.writes = writes
        result = self.rpc('initialize',{'protocolVersion':'2025-11-25','capabilities':{},
                     'clientInfo':{'name':'vericomedia-digest','version':'0.2.0'}})
        self.version = result['protocolVersion']
        self.rpc('notifications/initialized', notification=True)

    def rpc(self, method, params=None, notification=False, write=False):
        self.counter += 1
        payload={'jsonrpc':'2.0','method':method}
        if not notification:payload['id']=self.counter
        if params is not None:payload['params']=params
        for attempt in range(1 if write else 3):
            headers={'Content-Type':'application/json','Accept':'application/json, text/event-stream',
                     'Authorization':'Bearer '+self.token}
            if self.session:headers['Mcp-Session-Id']=self.session
            if self.version:headers['MCP-Protocol-Version']=self.version
            try:
                req=urllib.request.Request(self.endpoint,data=json.dumps(payload).encode(),headers=headers)
                with urllib.request.urlopen(req,timeout=45) as response:
                    self.session=response.headers.get('Mcp-Session-Id',self.session)
                    if notification or response.status==202:return {}
                    if 'text/event-stream' in response.headers.get('Content-Type',''):
                        lines=[]; total=0; data=None; started=time.monotonic()
                        while time.monotonic()-started<60:
                            line=response.readline(1_000_000).decode().rstrip('\r\n')
                            total+=len(line)
                            if total>2_000_000:raise PipelineError('mcp_response_too_large')
                            if line.startswith('data:'):lines.append(line[5:].strip())
                            elif not line and lines:
                                item=json.loads('\n'.join(lines));lines=[]
                                if item.get('id')==self.counter:data=item;break
                            elif not line and not lines:
                                # Empty line is an SSE boundary, not necessarily EOF.
                                continue
                        if data is None:raise PipelineError('mcp_missing_response')
                    else:data=json.loads(response.read(2_000_001))
                if 'error' in data:raise PipelineError('mcp_rpc_error')
                return data.get('result',{})
            except urllib.error.HTTPError as error:
                if write:raise UnknownOutcome('mcp_write_outcome_unknown') from None
                if error.code not in (429,502,503,504) or attempt==2:
                    raise PipelineError('mcp_http_'+str(error.code)) from None
                time.sleep(2**attempt)
            except (urllib.error.URLError,OSError,TimeoutError):
                if write:raise UnknownOutcome('mcp_write_outcome_unknown') from None
                if attempt==2:raise PipelineError('mcp_read_failed') from None
                time.sleep(2**attempt)
        raise PipelineError('mcp_failed')

    def call(self, name, arguments):
        write=name in WRITE_TOOLS
        if name not in READ_TOOLS|WRITE_TOOLS or (write and not self.writes):
            raise PipelineError('mcp_tool_not_allowed')
        if write and arguments.get('projectid')!=14191605:raise PipelineError('wrong_write_project')
        result=self.rpc('tools/call',{'name':name,'arguments':arguments},write=write)
        if result.get('isError'):
            if write:raise UnknownOutcome('mcp_write_tool_error')
            raise PipelineError('mcp_read_tool_error')
        text=[c['text'] for c in result.get('content',[]) if c.get('type')=='text']
        if len(text)==1:
            try:return json.loads(text[0])
            except ValueError:return text[0]
        return result

    def catalog(self):
        tools=[];cursor=None
        for _ in range(20):
            result=self.rpc('tools/list',{'cursor':cursor} if cursor else {})
            tools.extend(result.get('tools',[]));cursor=result.get('nextCursor')
            if not cursor:return tools
        raise PipelineError('mcp_catalog_truncated')
