import json
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch,Mock
from vericomedia_publisher.digest.common import ROOT,PipelineError,UnknownOutcome,period
from vericomedia_publisher.digest import fixtures
from vericomedia_publisher.digest.editorial import verify_research,validate_article
from vericomedia_publisher.digest.render import render,scope_css
from vericomedia_publisher.digest.pipeline import run,preflight
from vericomedia_publisher.digest.mcp import MCP
from vericomedia_publisher.digest.journal import GitHubJournal
from vericomedia_publisher.digest.publish import publish


class DigestTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.out=Path(self.temp.name)/'run'
        self.config=json.loads((ROOT/'config/digest.json').read_text())
        self.window=period('2026-11-01')
        self.research=fixtures.research(self.window)

    def test_exact_periods(self):
        self.assertEqual(period('2026-11-01')['start'],'2026-10-26')
        self.assertEqual(period('2026-11-08')['end'],'2026-11-07')
        with self.assertRaises(PipelineError):period('2027-11-01')

    def test_complete_fixture_has_separate_editing_and_all_outputs(self):
        result=run('2026-11-01','fixture',self.out,qa=lambda *a:{'passed':True})
        for name in ('research.json','draft.md','edited.md','article.html','publication-report.json'):
            self.assertTrue((self.out/name).exists())
        self.assertNotEqual((self.out/'draft.md').read_text(),(self.out/'edited.md').read_text())
        self.assertTrue(result['fixture_only']);self.assertFalse(result['published'])
        self.assertEqual(result['estimated_usd'],0)

    def test_live_mode_blocked_before_network(self):
        with patch('vericomedia_publisher.digest.pipeline.OpenAI') as llm:
            with self.assertRaises(PipelineError):run('2026-11-01','publish',self.out)
            llm.assert_not_called()
        self.assertFalse((self.out/'article.html').exists())

    def test_missing_api_key_is_explicit_and_no_publish(self):
        with patch.dict('os.environ',{},clear=True):
            with self.assertRaisesRegex(PipelineError,'missing_VERICO_LLM_API_KEY'):
                run('2026-11-01','dry-run',self.out)
        self.assertFalse(json.loads((self.out/'publication-report.json').read_text())['published'])

    def test_existing_output_is_never_overwritten(self):
        self.out.mkdir();(self.out/'draft.md').write_text('keep')
        with self.assertRaises(PipelineError):run('2026-11-01','fixture',self.out)
        self.assertEqual((self.out/'draft.md').read_text(),'keep')

    def test_out_of_period_and_duplicate_news_rejected(self):
        for change in ('date','duplicate','count'):
            r=deepcopy(self.research)
            if change=='date':r['news'][0]['event_date']='2026-10-25'
            if change=='duplicate':r['news'][1]['primary_url']=r['news'][0]['primary_url']
            if change=='count':r['news']=r['news'][:2]
            with self.subTest(change=change),self.assertRaises(PipelineError):
                verify_research(r,self.window,self.config,fetch=fixtures.source)

    def test_unfetched_or_fabricated_quote_rejected(self):
        self.research['news'][0]['quote']='This quotation is not present in source documents.'
        with self.assertRaisesRegex(PipelineError,'source_evidence_not_found'):
            verify_research(self.research,self.window,self.config,fetch=fixtures.source)

    def test_factcheck_failure_prevents_html(self):
        class BadModel(fixtures.FixtureModel):
            def json(self,*args,**kwargs):
                r=super().json(*args,**kwargs)
                if self.calls==4:r['passed']=False
                return r
        with self.assertRaises(PipelineError):
            run('2026-11-01','fixture',self.out,model=BadModel(self.window))
        self.assertTrue((self.out/'edited.md').exists());self.assertFalse((self.out/'article.html').exists())

    def test_editor_must_leave_editing_evidence(self):
        class BadEditor(fixtures.FixtureModel):
            def json(self,*args,**kwargs):
                r=super().json(*args,**kwargs)
                if self.calls==3:r.pop('editing_notes')
                return r
        with self.assertRaisesRegex(PipelineError,'editing_pass_missing'):
            run('2026-11-01','fixture',self.out,model=BadEditor(self.window))

    def test_unknown_source_and_invented_quote_rejected(self):
        r=verify_research(self.research,self.window,self.config,fetch=fixtures.source)
        for kind in ('unknown','quote','conclusion'):
            a=fixtures.article()
            if kind=='unknown':a['sections'][0]['source_ids']=['missing']
            if kind=='quote':a['sections'][0]['quote']='Invented quotation'
            if kind=='conclusion':a['sections'][0]['heading']='Выводы'
            with self.subTest(kind=kind),self.assertRaises(PipelineError):validate_article(a,r)

    def test_template_scopes_css_and_escapes_data(self):
        a=fixtures.article();a['title']='<img src=x onerror=alert(1)>'
        fragment=render(a,self.research,self.config,self.window)
        self.assertIn('&lt;img',fragment);self.assertNotIn('<img src=x',fragment)
        self.assertNotIn('#article-form',fragment);self.assertIn('#popup:popupzayavka',fragment)
        self.assertNotIn('src="https://static.tildacdn.com/tild6535',fragment)
        self.assertIn('og:image',fragment)
        self.assertEqual(scope_css('.x,.y{color:red}@media(max-width:10px){.z{color:blue}}'),
                         '.vg-article .x,.vg-article .y{color:red}\n@media(max-width:10px){.vg-article .z{color:blue}}')

    def test_readonly_mcp_client_refuses_write_tools(self):
        c=object.__new__(MCP);c.writes=False;c.rpc=Mock()
        with self.assertRaises(PipelineError):c.call('publish_page',{'projectid':14191605,'pageid':1})
        c.rpc.assert_not_called()

    def test_existing_remote_slug_stops_before_claim(self):
        config=self.config|dict(live_enabled=True,regulation_approved=True,badge_live_test_passed=True,production_runner_verified=True)
        client=Mock()
        client.call.side_effect=[[{'id':'14191605','url':'https://vericomedia.ru'}],[{'alias':self.window['slug']}]]
        journal=Mock()
        with self.assertRaisesRegex(PipelineError,'remote_slug_already_exists'):
            publish(config,self.window|{'complete_week':True},fixtures.article(),'html',{'passed':True},client,journal)
        journal.claim.assert_not_called()

    def test_durable_existing_claim_never_overwritten(self):
        journal=GitHubJournal('verico26/vericomedia-publisher',token='synthetic')
        journal.ensure_branch=Mock();journal.read=Mock(return_value={'sha':'existing','data':{'status':'claimed'}});journal.put=Mock()
        with self.assertRaises(PipelineError):journal.claim(self.window['slug'],{})
        journal.put.assert_not_called()

    def test_publish_unknown_outcome_reads_before_any_retry(self):
        config=self.config|dict(live_enabled=True,regulation_approved=True,badge_live_test_passed=True,production_runner_verified=True)
        a=fixtures.article();existing={'id':'42','alias':'existing','published':'old'}
        class Client:
            def __init__(self,published):self.published=published;self.publish_count=0;self.created=False;self.code='';self.settings={}
            def call(self,name,args):
                if name=='get_projects':return [{'id':'14191605','url':'https://vericomedia.ru'}]
                if name=='get_pages':return [existing]+([{'id':'99','alias':self.settings.get('alias','')}] if self.created else [])
                if name=='get_project_settings':return {'unchanged':True}
                if name=='add_blank_page':self.created=True;return 99
                if name=='get_page_settings':return {'date':'2026-11-01 10:00','published':'123' if self.publish_count and self.published else ''}|self.settings
                if name=='describe_tool':return {'inputSchema':{'properties':{'date':{'type':'string'}}}}
                if name=='update_page_settings':self.settings.update(args);return 'OK'
                if name=='tpls_list':return [{'cod':'T123','id':'131'}]
                if name=='add_record':return {'recordid':100}
                if name=='edit_record':return {'fields':{'code':{}},'record':{'code':self.code}}
                if name=='update_record':self.code=args['fields']['code'];return 'OK'
                if name=='publish_page':self.publish_count+=1;raise UnknownOutcome('timeout')
                raise AssertionError(name)
        class Journal:
            def claim(self,key,data):return {'sha':'a','data':data}
            def update(self,key,record,data):return {'sha':'b','data':data}
        for did_publish in (False,True):
            c=Client(did_publish)
            with self.subTest(did_publish=did_publish),patch('vericomedia_publisher.digest.publish.fetch_public',return_value=a['seo_title']+' data-verico-digest'):
                if did_publish:
                    result=publish(config,self.window|{'complete_week':True},a,'test html',{'passed':True},c,Journal())
                    self.assertEqual(result['status'],'published')
                else:
                    with self.assertRaises(UnknownOutcome):publish(config,self.window|{'complete_week':True},a,'test html',{'passed':True},c,Journal())
                self.assertEqual(c.publish_count,1)
