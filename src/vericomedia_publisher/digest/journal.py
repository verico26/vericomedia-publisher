"""Durable metadata journal on a dedicated GitHub branch, using API CAS.

No article text or credentials. A pre-write claim blocks reruns after unknown outcomes.
"""
import base64
import json
import os
import urllib.parse
import urllib.request
import urllib.error
from .common import PipelineError

class GitHubJournal:
    branch='publication-state'
    def __init__(self, repository, token=None):
        if repository!='verico26/vericomedia-publisher':raise PipelineError('unexpected_state_repository')
        self.repository=repository
        self.token=token or os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')
        if not self.token:raise PipelineError('missing_github_state_token')

    def api(self, method, path, body=None, missing=False):
        headers={'Authorization':'Bearer '+self.token,'Accept':'application/vnd.github+json',
                 'X-GitHub-Api-Version':'2022-11-28','Content-Type':'application/json'}
        req=urllib.request.Request('https://api.github.com/repos/'+self.repository+path,
            data=json.dumps(body).encode() if body is not None else None,headers=headers,method=method)
        try:
            with urllib.request.urlopen(req,timeout=25) as r:return json.load(r)
        except urllib.error.HTTPError as error:
            if error.code==404 and missing:return None
            raise PipelineError('github_state_request_failed_'+str(error.code)) from None
        except (urllib.error.URLError,OSError):raise PipelineError('github_state_outcome_unknown') from None

    def path(self,key):
        if not key.startswith('news/') or '..' in key or not all(c.isalnum() or c in '/-' for c in key):
            raise PipelineError('invalid_state_key')
        return '/contents/.publication-state/14191605/'+key.replace('/','--')+'.json'

    def read(self,key):
        r=self.api('GET',self.path(key)+'?ref='+self.branch,missing=True)
        if r is None:return None
        return {'sha':r['sha'],'data':json.loads(base64.b64decode(r['content']))}

    def ensure_branch(self):
        if self.api('GET','/git/ref/heads/'+self.branch,missing=True):return
        repo=self.api('GET','')
        ref=self.api('GET','/git/ref/heads/'+urllib.parse.quote(repo['default_branch'],safe=''))
        self.api('POST','/git/refs',{'ref':'refs/heads/'+self.branch,'sha':ref['object']['sha']})

    def put(self,key,data,sha=None):
        body={'message':'Record digest publication state','branch':self.branch,
              'content':base64.b64encode(json.dumps(data,sort_keys=True).encode()).decode()}
        if sha:body['sha']=sha
        r=self.api('PUT',self.path(key),body)
        return {'sha':r['content']['sha'],'data':data}

    def claim(self,key,data):
        self.ensure_branch()
        if self.read(key) is not None:raise PipelineError('existing_or_unresolved_publication_claim')
        # If another caller wins after read, PUT without SHA fails closed; never overwrite.
        return self.put(key,data)

    def update(self,key,record,data):
        return self.put(key,data,record['sha'])
