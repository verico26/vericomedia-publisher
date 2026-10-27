import argparse
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from .common import ROOT, PipelineError, period, dump, fetch_public
from .llm import OpenAI
from .editorial import RESEARCH, WRITER, EDITOR, FACTCHECK, verify_research, validate_article, markdown
from .render import render, document
from .qa import check, check_public
from .fixtures import FixtureModel, source as fixture_source
from .mcp import MCP
from .publish import publish

LOG=logging.getLogger('vericomedia.digest')


def preflight(output,client=None):
    client=client or MCP()
    catalog=client.catalog()
    required={'get_projects','get_pages','add_blank_page','update_page_settings','add_record','edit_record','update_record','publish_page'}
    names={t['name'] for t in catalog}
    if not required<=names:raise PipelineError('required_mcp_tool_missing')
    projects=client.call('get_projects',{})
    project=next((p for p in projects if str(p['id'])=='14191605'),None)
    if not project or project.get('url','').rstrip('/')!='https://vericomedia.ru':
        raise PipelineError('target_project_not_verified')
    pages=client.call('get_pages',{'projectid':14191605})
    report={'mode':'preflight','mcp_read_verified':True,'projectid':14191605,'page_count':len(pages),
            'required_tool_names':sorted(required),'writes_tested':False,'published':False}
    dump(Path(output)/'publication-report.json',report)
    return report


def run(publication_date,mode,output,config=None,model=None,qa=None,now=None):
    config=config or json.loads((ROOT/'config/digest.json').read_text())
    output=Path(output)
    if output.exists() and any(output.iterdir()):raise PipelineError('output_directory_not_empty')
    output.mkdir(parents=True,exist_ok=True)
    report={'mode':mode,'publication_date':publication_date,'status':'started','published':False,'fixture_only':mode=='fixture'}
    stage='configuration';llm=None
    try:
        if mode=='preflight':
            report.update(preflight(output));report['status']='preflight_passed';return report
        if mode not in ('fixture','dry-run','publish'):raise PipelineError('unsupported_mode')
        window=period(publication_date)
        now=now or datetime.now(timezone.utc)
        window['complete_week']=now.date()>datetime.fromisoformat(window['end']).date()
        if mode=='publish':
            if not all(config.get(k) is True for k in ('live_enabled','regulation_approved','badge_live_test_passed','production_runner_verified','existing_popup_verified')):
                raise PipelineError('live_publication_not_approved_or_unverified')
            if now.date().isoformat()!=publication_date or not window['complete_week']:
                raise PipelineError('wrong_live_publication_date')
        llm=model or (FixtureModel(window) if mode=='fixture' else OpenAI(config))
        stage='research';LOG.info('stage=%s',stage)
        research=llm.json(RESEARCH,{'window':window},search=True)
        # Save even unverified research if the following gate fails.
        dump(output/'research.json',research)
        research=verify_research(research,window,config,fetch=fixture_source if mode=='fixture' else fetch_public)
        dump(output/'research.json',research)
        reference=(ROOT/'assets/verico-style-reference.txt').read_text()
        if mode=='publish' and research.get('fixture_only'):
            raise PipelineError('synthetic_research_not_publishable')
        stage='draft';LOG.info('stage=%s',stage)
        draft=validate_article(llm.json(WRITER,{'research':research,'voice_reference':reference}),research)
        dump(output/'draft.json',draft)
        (output/'draft.md').write_text(markdown(draft,research))
        stage='editing';LOG.info('stage=%s',stage)
        edited=validate_article(llm.json(EDITOR,{'draft':draft,'research':research,'voice_reference':reference}),research)
        if not edited.get('editing_notes'):raise PipelineError('editing_pass_missing')
        dump(output/'edited.json',edited)
        (output/'edited.md').write_text(markdown(edited,research))
        stage='factcheck';LOG.info('stage=%s',stage)
        verification=llm.json(FACTCHECK,{'article':edited,'research':research})
        dump(output/'factcheck.json',verification)
        if verification.get('passed') is not True or verification.get('event_dates_verified') is not True or verification.get('problems') or set(verification.get('checked_source_ids',[]))!={n['id'] for n in research['news']}:
            raise PipelineError('editorial_factcheck_failed')
        stage='render';LOG.info('stage=%s',stage)
        fragment=render(edited,research,config,window)
        (output/'article.html').write_text(fragment)
        (output/'preview.html').write_text(document(fragment,edited))
        stage='layout';LOG.info('stage=%s',stage)
        result=(qa or check)(fragment,edited,research,output/'screenshots')
        if not result.get('passed'):raise PipelineError('layout_check_failed')
        report.update(status='dry_run_passed',window=window,quality=result,
                      sources=[{'id':n['id'],'url':n['primary_url'],'event_date':n['event_date']} for n in research['news']])
        if mode=='publish':
            stage='existing_links'
            for link in config['related']+config['tools']:fetch_public(link['url'],['vericomedia.ru'])
            stage='publish';LOG.info('stage=%s',stage)
            report.update(publish(config,window,edited,fragment,result))
            report['published']=True
            stage='public_layout'
            report['public_quality']=check_public(report['url'],edited,output/'screenshots')
        return report
    except Exception as error:
        report.update(status='failed',failed_stage=stage,error_code=str(error) if isinstance(error,PipelineError) else type(error).__name__)
        raise
    finally:
        if llm:report.update(model=config['model'] if mode!='fixture' else 'synthetic_fixture',usage=llm.usage,estimated_usd=llm.cost())
        dump(output/'publication-report.json',report)


def main(argv=None):
    parser=argparse.ArgumentParser(description='VericoMedia autonomous digest; real publishing disabled by deployment gates')
    parser.add_argument('--mode',choices=['fixture','dry-run','preflight','publish'],default='fixture')
    parser.add_argument('--publication-date',choices=['2026-11-01','2026-11-08'],default='2026-11-01')
    parser.add_argument('--output',type=Path,default=Path('artifacts/digest'))
    args=parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    try:
        run(args.publication_date,args.mode,args.output)
        LOG.info('pipeline_finished mode=%s',args.mode)
        return 0
    except Exception as error:
        # Never print remote response bodies, tokens or generated article contents.
        LOG.error('pipeline_failed error_type=%s',type(error).__name__)
        return 1


if __name__=='__main__':raise SystemExit(main())
