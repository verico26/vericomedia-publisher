"""Real Chromium checks. Local HTML checks are distinct from live Tilda acceptance."""
import asyncio
import json
import os
from pathlib import Path
from .render import document
from .common import PipelineError, dump

async def _check(fragment,article,research,output,executable=None):
    from playwright.async_api import async_playwright
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    reports=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True,executable_path=executable)
        context=await browser.new_context(service_workers='block')
        badge=False
        async def handler(route):
            if route.request.url=='https://fixture.invalid/badge.svg':
                await route.fulfill(content_type='image/svg+xml',body='<svg xmlns="http://www.w3.org/2000/svg" width="800" height="450"><rect width="800" height="450" fill="#35080d"/></svg>')
            elif route.request.url.startswith('https://fixture.invalid/article'):
                await route.fulfill(content_type='text/html',body=document(fragment,article,'https://fixture.invalid/badge.svg' if badge else None))
            else:await route.abort()
        await context.route('**/*',handler)
        page=await context.new_page()
        errors=[];page.on('pageerror',lambda _:errors.append('page_script_error'))
        await page.goto('https://fixture.invalid/article')
        for width in (1440,768,390,360,320):
            await page.set_viewport_size({'width':width,'height':960})
            await page.screenshot(path=str(output/f'viewport-{width}.png'),full_page=True)
            result=await page.evaluate('''() => {
                const root=document.querySelector('.vg-article'),text=root.querySelector('.vg-content p'),h=root.querySelector('h1');
                const overflow=[...root.querySelectorAll('*')].filter(e=>{const r=e.getBoundingClientRect();return r.width&&r.right>innerWidth+1}).length;
                return {width:innerWidth,document_width:document.documentElement.scrollWidth,h1_count:root.querySelectorAll('h1').length,
                  body_font:parseFloat(getComputedStyle(text).fontSize),h1_font:parseFloat(getComputedStyle(h).fontSize),overflow_count:overflow,
                  cover_hidden:root.querySelector('.vg-cover').hidden,grid:getComputedStyle(root.querySelector('.vg-shell')).gridTemplateColumns};}''')
            if result['document_width']>width or result['overflow_count'] or result['h1_count']!=1 or result['body_font']<16 or not result['cover_hidden']:
                raise PipelineError('responsive_layout_failed')
            if width<=650:
                details=page.locator('.vg-mobile-toc')
                await details.locator('summary').click()
                if await details.get_attribute('open') is None:raise PipelineError('mobile_toc_does_not_open')
                await details.locator('a').first.click()
                if '#news-' not in page.url:raise PipelineError('toc_anchor_failed')
                await details.locator('summary').click()
            for section in article['sections']:
                if await page.locator('#'+section['id']).count()!=1:raise PipelineError('missing_anchor')
            if await page.locator('a[href="#popup:popupzayavka"]').count()!=1:raise PipelineError('cta_missing')
            result['passed']=True;reports.append(result)
        badge=True
        await page.goto('https://fixture.invalid/article?badge=synthetic')
        await page.wait_for_function("!document.querySelector('.vg-cover').hidden")
        badge_src=await page.locator('.vg-cover img').get_attribute('src')
        if badge_src!='https://fixture.invalid/badge.svg':raise PipelineError('badge_cover_failed')
        await page.screenshot(path=str(output/'synthetic-badge.png'),full_page=True)
        if errors:raise PipelineError('article_script_error')
        await browser.close()
    result={'passed':True,'mode':'local_render','viewports':reports,'synthetic_badge_reload_passed':True,
            'real_tilda_badge_test_passed':False,'real_tilda_render_test_passed':False}
    dump(output/'qa.json',result)
    return result


def check(fragment,article,research,output):
    return asyncio.run(_check(fragment,article,research,output,os.environ.get('BROWSER_EXECUTABLE')))


async def _public(url,article,output):
    from playwright.async_api import async_playwright
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True,executable_path=os.environ.get('BROWSER_EXECUTABLE'))
        context=await browser.new_context(service_workers='block')
        page=await context.new_page()
        response=await page.goto(url,wait_until='networkidle',timeout=60000)
        if response.status!=200 or page.url.rstrip('/')!=url.rstrip('/'):
            raise PipelineError('public_url_or_http_failed')
        if await page.title()!=article['seo_title'] or await page.locator('meta[name="description"]').get_attribute('content')!=article['description']:
            raise PipelineError('public_seo_failed')
        if await page.locator('.vg-article h1').inner_text()!=article['title']:
            raise PipelineError('public_h1_failed')
        results=[]
        for width in (1440,768,390,360,320):
            await page.set_viewport_size({'width':width,'height':960})
            await page.wait_for_timeout(300)
            metric=await page.evaluate('({width:innerWidth,scrollWidth:document.documentElement.scrollWidth})')
            if metric['scrollWidth']>width:raise PipelineError('public_horizontal_overflow')
            if width<=650:
                await page.locator('.vg-mobile-toc summary').click()
                await page.locator('.vg-mobile-toc a').first.click()
                if '#news-' not in page.url:raise PipelineError('public_toc_failed')
                await page.locator('.vg-mobile-toc summary').click()
            await page.screenshot(path=str(output/f'public-{width}.png'),full_page=True)
            results.append(metric)
        if await page.locator('.vg-related__grid a').count()!=6:raise PipelineError('public_cards_failed')
        for section in article['sections']:
            node=page.locator('#'+section['id'])
            if await node.count()!=1 or not await node.locator('.vg-sources a').count():raise PipelineError('public_source_or_anchor_missing')
        await browser.close()
    report={'passed':True,'url':url,'http_status':200,'viewports':results,'mode':'real_public_browser'}
    dump(output/'qa-public.json',report)
    return report


def check_public(url,article,output):
    return asyncio.run(_public(url,article,output))
