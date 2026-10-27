"""Create only a new /news/ page. Caller must pass every deployment gate first."""
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from .common import PipelineError, UnknownOutcome, digest, fetch_public
from .mcp import MCP
from .journal import GitHubJournal


def prepare_settings(client,page,window,article):
    old=client.call('get_page_settings',{'projectid':14191605,'pageid':page})
    schema=client.call('describe_tool',{'tool_name':'update_page_settings'})['inputSchema']['properties']
    args={'projectid':14191605,'pageid':page}
    for name,prop in schema.items():
        if name in args or name not in old:continue
        value=old[name]
        if prop.get('type')=='integer':value=int(value or 0)
        if name=='date':value=value[:16]
        args[name]=value
    args.update(title=article['title'],alias=window['slug'],meta_title=article['seo_title'],meta_descr=article['description'])
    args.setdefault('date',datetime.now(ZoneInfo('Asia/Novosibirsk')).strftime('%Y-%m-%d %H:%M'))
    return args


def validate_gate(config,mode,qa,window):
    if mode!='publish' or not all(config.get(k) is True for k in
        ('live_enabled','regulation_approved','badge_live_test_passed','production_runner_verified')):
        raise PipelineError('live_publication_not_approved_or_unverified')
    if not qa.get('passed') or not window.get('complete_week'):
        raise PipelineError('publication_quality_or_period_gate_failed')
    if not window['slug'].startswith('news/') or '..' in window['slug']:
        raise PipelineError('publication_outside_news')


def publish(config,window,article,fragment,qa,client=None,journal=None):
    validate_gate(config,'publish',qa,window)
    c=client or MCP(writes=True)
    journal=journal or GitHubJournal('verico26/vericomedia-publisher')
    projects=c.call('get_projects',{})
    if not any(str(p.get('id'))=='14191605' and p.get('url','').rstrip('/')=='https://vericomedia.ru' for p in projects):
        raise PipelineError('wrong_publication_project')
    pages=c.call('get_pages',{'projectid':14191605})
    if any(p.get('alias')==window['slug'] or p.get('url')==window['slug'] for p in pages):
        raise PipelineError('remote_slug_already_exists')
    project_before=c.call('get_project_settings',{'projectid':14191605})
    claim=journal.claim(window['slug'],{'status':'claimed','projectid':14191605,'slug':window['slug'],'html_sha256':digest(fragment)})
    page=None
    try:
        page=int(c.call('add_blank_page',{'projectid':14191605}))
        if any(int(p['id'])==page for p in pages):raise PipelineError('new_page_identity_collision')
        claim=journal.update(window['slug'],claim,claim['data']|{'status':'page_created','pageid':page})
        c.call('update_page_settings',prepare_settings(c,page,window,article))
        templates=c.call('tpls_list',{'query':'HTML'})
        tpl=next((t for t in templates if t.get('cod')=='T123'),None)
        if not tpl:raise PipelineError('t123_not_available')
        rec=c.call('add_record',{'projectid':14191605,'pageid':page,'tplid':int(tpl['id'])})
        record=int(rec['recordid'])
        c.call('describe_tool',{'tool_name':'edit_record'})
        content=c.call('edit_record',{'projectid':14191605,'pageid':page,'recordid':record,'tab':'content'})
        if 'code' not in content['fields']:raise PipelineError('t123_code_field_missing')
        c.call('describe_tool',{'tool_name':'update_record'})
        c.call('update_record',{'projectid':14191605,'pageid':page,'recordid':record,'tab':'content','only_field':'code','fields':{'code':fragment}})
        current=c.call('edit_record',{'projectid':14191605,'pageid':page,'recordid':record,'tab':'content'})
        settings=c.call('get_page_settings',{'projectid':14191605,'pageid':page})
        if current['record']['code']!=fragment or settings['alias']!=window['slug'] or settings['meta_title']!=article['seo_title'] or settings['meta_descr']!=article['description']:
            raise PipelineError('draft_readback_failed')
        claim=journal.update(window['slug'],claim,claim['data']|{'status':'publish_claimed','recordid':record})
        try:
            response=c.call('publish_page',{'projectid':14191605,'pageid':page})
        except UnknownOutcome:
            # Read first. Never call publish a second time on an ambiguous outcome.
            settings=c.call('get_page_settings',{'projectid':14191605,'pageid':page})
            if not settings.get('published'):raise
            response={'link':'https://vericomedia.ru/'+window['slug'],'reconciled_after_unknown_outcome':True}
        url='https://vericomedia.ru/'+window['slug']
        if response.get('link')!=url:raise PipelineError('unexpected_publication_url')
        public=fetch_public(url,['vericomedia.ru'])
        if article['seo_title'] not in public or 'data-verico-digest' not in public:
            raise PipelineError('public_content_check_failed')
        after=c.call('get_pages',{'projectid':14191605})
        bi={p['id']:p for p in pages};ai={p['id']:p for p in after}
        if any(ai.get(i)!=p for i,p in bi.items()):raise PipelineError('other_page_metadata_changed')
        if c.call('get_project_settings',{'projectid':14191605})!=project_before:
            raise PipelineError('project_settings_changed')
        index=fetch_public('https://vericomedia.ru/news/',['vericomedia.ru'])
        result={'status':'published','pageid':page,'url':url,'other_pages_unchanged':True,
                'appears_in_news_index':window['slug'] in index,'recordid':record}
        journal.update(window['slug'],claim,claim['data']|result)
        return result
    except Exception:
        # Leave the durable claim unresolved; no deletion, rollback or duplicate write.
        raise
