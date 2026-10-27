"""Report secret presence only; authenticate MCP read-only if configured."""
import json
import os
from vericomedia_publisher.digest.mcp import MCP
from vericomedia_publisher.digest.pipeline import preflight

names=('TILDA_MCP_TOKEN','VERICO_LLM_API_KEY','VERICO_ARTIFACT_KEY')
report={'configured':{n:bool(os.environ.get(n)) for n in names},'authenticated_mcp_verified':False}
if report['configured']['TILDA_MCP_TOKEN']:
    result=preflight('artifacts/runner-preflight',client=MCP())
    report['authenticated_mcp_verified']=result['mcp_read_verified']
print(json.dumps(report))
