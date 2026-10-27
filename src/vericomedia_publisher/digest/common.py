import hashlib
import json
import os
import re
import urllib.request
import urllib.parse
import urllib.error
import ipaddress
import socket
from datetime import date, datetime, timezone
from pathlib import Path
from html.parser import HTMLParser

ROOT = Path(__file__).resolve().parents[3]
DATES = {
    '2026-11-01': ('2026-10-26', '2026-10-31', 'news/novosti-marketinga-26-31-oktyabrya-2026'),
    '2026-11-08': ('2026-11-02', '2026-11-07', 'news/novosti-marketinga-2-7-noyabrya-2026'),
}

class PipelineError(RuntimeError):
    pass

class UnknownOutcome(PipelineError):
    """A write may have completed. Read/reconcile; do not retry automatically."""


def period(publication_date):
    try:
        start, end, slug = DATES[publication_date]
    except KeyError:
        raise PipelineError('unsupported_publication_date') from None
    return {'publication_date': publication_date, 'start': start, 'end': end, 'slug': slug}


def dump(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def safe_url(url, allowed):
    p = urllib.parse.urlsplit(url)
    host = p.hostname or ''
    if p.scheme != 'https' or p.username or p.password or p.port not in (None, 443):
        raise PipelineError('unsafe_url')
    if not any(host == d or host.endswith('.' + d) for d in allowed):
        raise PipelineError('url_host_not_allowed')
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError:
        raise PipelineError('source_dns_failed') from None
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise PipelineError('nonpublic_source_address')
    return url


class CheckedRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed):
        self.allowed = allowed
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        safe_url(newurl, self.allowed)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_public(url, allowed, limit=2_000_000):
    safe_url(url, allowed)
    opener = urllib.request.build_opener(CheckedRedirect(allowed))
    try:
        with opener.open(urllib.request.Request(url, headers={'User-Agent':'VericoMediaResearch/0.1','Accept-Encoding':'identity'}), timeout=25) as r:
            raw = r.read(limit + 1)
            if r.status != 200 or len(raw) > limit:
                raise PipelineError('source_response_invalid')
            if 'text/html' not in r.headers.get('Content-Type', ''):
                raise PipelineError('source_not_html')
            return raw.decode(r.headers.get_content_charset() or 'utf-8', errors='replace')
    except (urllib.error.URLError, OSError):
        raise PipelineError('public_fetch_failed') from None


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(); self.skip = 0; self.parts = []
    def handle_starttag(self, tag, attrs):
        if tag in ('script','style','noscript'): self.skip += 1
    def handle_endtag(self, tag):
        if tag in ('script','style','noscript'): self.skip = max(0, self.skip - 1)
    def handle_data(self, data):
        if not self.skip and data.strip(): self.parts.append(data.strip())


def text_of(html):
    p = VisibleText(); p.feed(html)
    return re.sub(r'\s+', ' ', ' '.join(p.parts))
