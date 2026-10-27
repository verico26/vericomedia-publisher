"""Executable synthetic browser prototype. No Tilda write adapter exists."""
import argparse
import hashlib
import json
import logging
import re
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlsplit

LOG = logging.getLogger(__name__)
ORIGIN = 'https://fixture.invalid'


class PrototypeError(RuntimeError):
    pass


def https_image(value):
    url = urlsplit(value)
    if url.scheme != 'https' or not url.hostname or url.username or url.password:
        raise ValueError('HTTPS image URL required')
    return value


def load_spec(path):
    data = json.loads(Path(path).read_text())
    for key in ('article_id', 'title', 'seo_title', 'description', 'html'):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError('Required article field')
    if data.get('project_name') != 'VericoMedia':
        raise ValueError('Unexpected project name')
    if not re.fullmatch(r'automation-test-[a-z0-9-]+', data.get('slug', '')):
        raise ValueError('Test slug required')
    if data.get('noindex') is not True or data.get('enabled') is not False:
        raise ValueError('Only disabled noindex test specs allowed')
    if data.get('cover_source') != 'page-badge':
        raise ValueError('Explicit cover source required')
    https_image(data['page_image_url'])
    return data


def badge_from_api_metadata(data):
    """Candidate, not proof of badge semantics. No network or key usage."""
    for key in ('featureimg', 'img'):
        if data.get(key):
            return {'url': https_image(data[key]), 'source': key, 'verified': False}
    raise ValueError('No image candidate; explicit image required')


def read_retry(action, attempts=3):
    # Only reads/assertions. Do not retry create/save/upload after a timeout.
    for attempt in range(attempts):
        try:
            return action()
        except (PrototypeError, TimeoutError):
            if attempt + 1 == attempts:
                raise
            LOG.warning('read_retry attempt=%d', attempt + 1)
            time.sleep(0.05 * (2 ** attempt))


class DraftLedger:
    def __init__(self, path):
        self.path = path
        with sqlite3.connect(path) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS draft_claims (
                project TEXT, slug TEXT, article_id TEXT, digest TEXT,
                status TEXT CHECK(status IN ('claimed','draft_saved')), remote_id TEXT,
                PRIMARY KEY(project, slug), UNIQUE(project, article_id))''')

    def claim(self, spec):
        digest = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
        with sqlite3.connect(self.path, timeout=30) as db:
            cursor = db.execute('''INSERT INTO draft_claims
                (project,slug,article_id,digest,status) VALUES (?,?,?,?,'claimed')
                ON CONFLICT DO NOTHING''',
                (spec['project_name'], spec['slug'], spec['article_id'], digest))
            return cursor.rowcount == 1

    def saved(self, spec, remote_id):
        if not remote_id:
            raise PrototypeError('Missing draft identity')
        with sqlite3.connect(self.path) as db:
            cursor = db.execute('''UPDATE draft_claims SET status='draft_saved',remote_id=?
                WHERE project=? AND slug=? AND article_id=? AND status='claimed' ''',
                (remote_id, spec['project_name'], spec['slug'], spec['article_id']))
            if cursor.rowcount != 1:
                raise PrototypeError('Pending claim missing')


class FixtureEditor:
    """Selectors belong ONLY to tests/fixtures/editor.html, never to Tilda."""
    def __init__(self, page):
        if page.url != ORIGIN + '/editor':
            raise PrototypeError('Only synthetic fixture origin supported')
        self.page = page

    def snapshot(self):
        return self.page.evaluate("JSON.parse(localStorage.getItem('drafts') || '[]')")

    def create_draft(self, spec, ledger, fail_after_create=False):
        if self.page.locator('#auth').inner_text() != 'Authenticated fixture user':
            raise PrototypeError('Reauthentication required')
        if any(d.get('slug') == spec['slug'] for d in read_retry(self.snapshot)):
            raise PrototypeError('Remote duplicate')
        if not ledger.claim(spec):
            raise PrototypeError('Existing or unresolved claim; reconcile manually')
        # Each write is performed exactly once, even on unknown outcome.
        self.page.get_by_role('button', name='Create test draft', exact=True).click()
        if fail_after_create:
            raise PrototypeError('Injected ambiguous timeout after create')
        values = {'Page title': spec['title'], 'SEO title': spec['seo_title'],
                  'Description': spec['description'], 'URL slug': spec['slug'],
                  'Page badge image': spec['page_image_url'],
                  'T123 HTML': spec['html']}
        for label, value in values.items():
            self.page.get_by_label(label, exact=True).fill(value)
        # Read back the badge field; do not assume separate SEO image = visual cover.
        badge = https_image(self.page.get_by_label('Page badge image', exact=True).input_value())
        self.page.get_by_label('Cover image', exact=True).fill(badge)
        self.page.get_by_label('Noindex', exact=True).check()
        self.page.get_by_role('button', name='Save draft', exact=True).click()
        def verify():
            matches = [d for d in self.snapshot() if d.get('slug') == spec['slug']]
            if len(matches) != 1 or matches[0].get('status') != 'draft':
                raise PrototypeError('Saved draft not confirmed')
            draft = matches[0]
            for key, expected in [('title',spec['title']), ('seo_title',spec['seo_title']),
                ('description',spec['description']), ('html',spec['html']),
                ('image',spec['page_image_url']), ('cover',spec['page_image_url']), ('noindex','on')]:
                if draft.get(key) != expected:
                    raise PrototypeError('Draft field mismatch')
            return draft['id']
        remote_id = read_retry(verify)
        ledger.saved(spec, remote_id)
        LOG.info('fixture_draft_verified publishing_enabled=false')
        return remote_id


def fixture_context(browser, fixture, storage_state=None, authenticated=True):
    context = browser.new_context(storage_state=storage_state, service_workers='block')
    def route_handler(route):
        if route.request.url == ORIGIN + '/editor':
            route.fulfill(body=fixture.read_text(), content_type='text/html')
        else:
            route.abort()
    context.route('**/*', route_handler)
    if storage_state is None and authenticated:
        context.add_cookies([{'name':'fixture_session', 'value':'synthetic',
                              'url':ORIGIN, 'httpOnly':False, 'secure':True}])
    return context


def run_demo(spec_path, fixture_path, output, executable=None):
    from playwright.sync_api import sync_playwright
    spec = load_spec(spec_path)
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=executable)
        context = fixture_context(browser, fixture_path)
        page = context.new_page()
        try:
            page.goto(ORIGIN + '/editor')
            draft_id = FixtureEditor(page).create_draft(spec, DraftLedger(output / 'drafts.sqlite3'))
            page.screenshot(path=str(output / 'fixture-draft.png'), full_page=True)
            # State remains in memory: no credentials or state artifact.
            restored = fixture_context(browser, fixture_path, storage_state=context.storage_state())
            other = restored.new_page()
            other.goto(ORIGIN + '/editor')
            if other.locator('#auth').inner_text() != 'Authenticated fixture user':
                raise PrototypeError('Fixture session restore failed')
            if len(FixtureEditor(other).snapshot()) != 1:
                raise PrototypeError('Fixture draft persistence failed')
            restored.close()
            result = {'fixture_only': True, 'tilda_integration_verified': False,
                      'draft_id': draft_id, 'session_restore_fixture': True,
                      'publishing_enabled': False, 'browser_version':browser.version}
            (output / 'result.json').write_text(json.dumps(result, indent=2))
        except Exception:
            # Safe only because this context cannot reach real authenticated pages.
            page.screenshot(path=str(output / 'fixture-error.png'), full_page=True)
            raise
        finally:
            context.close()
            browser.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description='Synthetic browser prototype; Tilda writes disabled')
    parser.add_argument('--target', choices=['fixture', 'tilda'], default='fixture')
    parser.add_argument('--spec', type=Path, default=Path('config/browser-test.json'))
    parser.add_argument('--fixture', type=Path, default=Path('tests/fixtures/editor.html'))
    parser.add_argument('--output', type=Path, default=Path('artifacts/browser'))
    parser.add_argument('--executable')
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    if args.target == 'tilda':
        LOG.error('live_tilda_disabled: authorization and verified UI adapter required')
        return 2
    try:
        run_demo(args.spec, args.fixture, args.output, args.executable)
        return 0
    except Exception as error:
        LOG.error('browser_prototype_failed error_type=%s', type(error).__name__)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
