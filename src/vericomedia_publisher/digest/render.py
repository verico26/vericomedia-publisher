"""Render escaped editorial data using the existing v2 visual system, locally scoped."""
import html
import json
import re
from .common import ROOT, PipelineError


def scope_css(css):
    result=[];position=0
    while position<len(css):
        opening=css.find('{',position)
        if opening<0:break
        header=css[position:opening].strip();depth=1;end=opening+1
        while end<len(css) and depth:
            if css[end]=='{':depth+=1
            elif css[end]=='}':depth-=1
            end+=1
        if depth:raise PipelineError('template_css_invalid')
        body=css[opening+1:end-1]
        if header.startswith('@media'):
            result.append(header+'{'+scope_css(body)+'}')
        elif header.startswith('@'):
            raise PipelineError('unexpected_template_css_at_rule')
        else:
            selectors=[s.strip() for s in header.split(',')]
            scoped=[s if s.startswith('.vg-article') else '.vg-article '+s for s in selectors]
            result.append(','.join(scoped)+'{'+body+'}')
        position=end
    return '\n'.join(result)


def inline(text):
    escaped=html.escape(text)
    return re.sub(r'\*\*([^*]+)\*\*',r'<strong>\1</strong>',escaped)


def cards(items,title,kind):
    expected='/news/' if kind=='related' else '/tools/'
    if len(items)!=3 or any(not item['url'].startswith('https://vericomedia.ru'+expected) for item in items):
        raise PipelineError('invalid_existing_links')
    return '<section class="vg-related"><h2>'+title+'</h2><div class="vg-related__grid">'+''.join(
        '<a href="'+html.escape(item['url'],quote=True)+'">'+html.escape(item['title'])+'</a>' for item in items)+'</div></section>'


def render(article,research,config,window):
    e=html.escape;sources={n['id']:n for n in research['news']}
    links=''.join('<a href="#'+s['id']+'">'+e(s['heading'])+'</a>' for s in article['sections'])
    body=[]
    for s in article['sections']:
        section='<section id="'+s['id']+'"><h2>'+e(s['heading'])+'</h2>'
        section+=''.join('<p>'+inline(p)+'</p>' for p in s['paragraphs'])
        if s.get('quote'):section+='<blockquote class="vg-quote">'+e(s['quote'])+'</blockquote>'
        if s.get('bullets'):section+='<ul>'+''.join('<li>'+inline(p)+'</li>' for p in s['bullets'])+'</ul>'
        section+='<p class="vg-sources">Источники: '+', '.join('<a href="'+e(sources[i]['primary_url'],quote=True)+'" rel="noopener">'+e(sources[i]['title'])+'</a>' for i in s['source_ids'])+'</p></section>'
        body.append(section)
    css=scope_css((ROOT/'assets/template-stati-v2.css').read_text())
    fixes='''.vg-article [hidden]{display:none!important}.vg-article .vg-author{width:auto;max-width:720px;margin:20px 0}.vg-article .vg-content p{margin:0 0 1.2em}.vg-article .vg-content a{color:#63212a;text-underline-offset:3px}.vg-article .vg-content{overflow-wrap:anywhere}.vg-article .vg-content section{scroll-margin-top:24px}.vg-article .vg-mobile-toc{display:none}.vg-article .vg-side a{border-radius:15px}.vg-article .vg-sources{font-size:14px;line-height:1.5}.vg-article .vg-caption{font-size:14px;line-height:1.5;color:#f5e4df}.vg-article .vg-related__grid{grid-template-columns:repeat(3,minmax(0,1fr))}.vg-article .vg-related__grid a{overflow-wrap:anywhere}.vg-article .vg-cover img{border-radius:15px}@media(max-width:650px){.vg-article .vg-toc{display:none}.vg-article .vg-mobile-toc{display:block;margin:0 0 24px;padding:14px;border:1px solid #ddcfc3;border-radius:15px}.vg-article .vg-mobile-toc summary{font-weight:bold;cursor:pointer}.vg-article .vg-mobile-toc a{display:block;margin:12px 0;color:#63212a}.vg-article .vg-related__grid{grid-template-columns:1fr}.vg-article .vg-author{margin:20px 0}.vg-article .vg-hero h1{font-size:clamp(29px,8vw,37px);overflow-wrap:anywhere}}'''
    # Existing mechanism: the cover reads page og:image after Tilda republishes metadata.
    # No image fallback, external image selection or global site mutation.
    ignored=json.dumps(config['ignored_badge_urls']).replace('<','\\u003c')
    script='''(()=>{const init=()=>{const root=document.querySelector('.vg-article[data-verico-digest]');if(!root)return;const meta=document.querySelector('meta[property="og:image"]');const fig=root.querySelector('.vg-cover'),img=fig.querySelector('img');const ignored=IGNORED;const sync=()=>{const value=meta&&meta.content;if(!value||ignored.includes(value))return;let u;try{u=new URL(value)}catch{return}if(u.protocol!=='https:')return;img.onload=()=>{fig.hidden=false};img.onerror=()=>{fig.hidden=true};img.src=u.href;};sync();if(meta)new MutationObserver(sync).observe(meta,{attributes:true,attributeFilter:['content']});};if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();})();'''.replace('IGNORED',ignored)
    return f'''<article class="vg-article vg-theme-wine" data-verico-digest="{e(window['slug'])}" aria-labelledby="vg-title">
<header class="vg-hero"><div class="vg-hero__inner"><p class="vg-kicker">Дайджест · {window['start']} - {window['end']}</p>
<h1 id="vg-title">{e(article['title'])}</h1><p class="vg-subtitle">{e(article['subtitle'])}</p>
<figure class="vg-cover" hidden><img alt="{e(article['title'],quote=True)}" loading="eager"></figure>
<p class="vg-caption">{e(article['description'])}</p><div class="vg-author"><span><strong>Верико</strong> · {window['publication_date']}</span></div><p class="vg-lead">{inline(article['lead'])}</p></div></header>
<div class="vg-shell"><aside class="vg-toc" aria-label="Содержание"><p>В статье</p>{links}</aside>
<main class="vg-content"><nav class="vg-crumbs" aria-label="Хлебные крошки"><a href="https://vericomedia.ru/">Главная</a><span>·</span><a href="https://vericomedia.ru/news/">Новости</a><span>·</span><span>{e(article['title'])}</span></nav>
<details class="vg-mobile-toc"><summary>В статье</summary><nav>{links}</nav></details>{''.join(body)}
{cards(config['related'],'Читайте также','related')}{cards(config['tools'],'Полезные инструменты','tools')}
</main><aside class="vg-side"><p class="vg-side__eyebrow">Нужна консультация?</p><p>Разберём предложение, посадочную и первые шаги рекламного запуска.</p><a href="#popup:popupzayavka">Обсудить задачу</a></aside></div></article><style>{css}\n{fixes}</style><script>{script}</script>'''


def document(fragment,article,badge=None):
    meta='<meta property="og:image" content="'+html.escape(badge,quote=True)+'">' if badge else ''
    return '<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+html.escape(article['seo_title'])+'</title><meta name="description" content="'+html.escape(article['description'],quote=True)+'">'+meta+'</head><body style="margin:0">'+fragment+'</body></html>'
