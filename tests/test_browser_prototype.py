import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vericomedia_publisher.browser_prototype import (
    DraftLedger, FixtureEditor, PrototypeError, badge_from_api_metadata,
    fixture_context, load_spec, main, read_retry, ORIGIN)

ROOT = Path(__file__).resolve().parents[1]


class PrototypeUnitTests(unittest.TestCase):
    def setUp(self):
        self.spec = load_spec(ROOT / 'config/browser-test.json')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger = DraftLedger(Path(self.tmp.name) / 'state.sqlite3')

    def test_live_target_disabled_before_browser_start(self):
        with patch('vericomedia_publisher.browser_prototype.run_demo') as demo:
            self.assertEqual(main(['--target', 'tilda']), 2)
            demo.assert_not_called()

    def test_duplicate_slug_or_article_id_blocks_even_changed_content(self):
        self.assertTrue(self.ledger.claim(self.spec))
        self.assertFalse(self.ledger.claim(self.spec | {'html':'different'}))
        self.assertFalse(self.ledger.claim(self.spec | {'article_id':'new'}))
        self.assertFalse(self.ledger.claim(self.spec | {'slug':'automation-test-other'}))

    def test_badge_candidate_is_not_claimed_verified(self):
        self.assertEqual(badge_from_api_metadata({'featureimg':'https://static.tildacdn.com/a.png'})['verified'], False)
        for data in ({}, {'img':'javascript:alert(1)'}, {'img':'https://user:password@example.com/a'}):
            with self.assertRaises(ValueError):
                badge_from_api_metadata(data)

    def test_reads_retry_but_stop(self):
        attempts = []
        def failing():
            attempts.append(1)
            raise PrototypeError('read failed')
        with self.assertRaises(PrototypeError):
            read_retry(failing)
        self.assertEqual(len(attempts), 3)

    def test_only_test_spec_allowed(self):
        for changes in ({'enabled':True}, {'slug':'production'}, {'noindex':False}):
            path = Path(self.tmp.name) / 'input.json'
            path.write_text(json.dumps(self.spec | changes))
            with self.assertRaises(ValueError):
                load_spec(path)


@unittest.skipUnless(os.environ.get('RUN_BROWSER_TESTS') == '1', 'Set RUN_BROWSER_TESTS=1 for real Chromium fixture tests')
class BrowserFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True,
                          executable_path=os.environ.get('BROWSER_EXECUTABLE'))

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.spec = load_spec(ROOT / 'config/browser-test.json')
        self.ledger = DraftLedger(Path(self.tmp.name) / 'state.sqlite3')
        self.context = fixture_context(self.browser, ROOT / 'tests/fixtures/editor.html')
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.page.goto(ORIGIN + '/editor')

    def tearDown(self):
        output = ROOT / 'artifacts/browser-tests'
        output.mkdir(parents=True, exist_ok=True)
        self.page.screenshot(path=str(output / f'fixture-{self._testMethodName}.png'), full_page=True)

    def test_draft_fields_and_session_restore(self):
        editor = FixtureEditor(self.page)
        self.assertEqual(editor.create_draft(self.spec, self.ledger), 'fixture-1')
        restored = fixture_context(self.browser, ROOT / 'tests/fixtures/editor.html',
                                   storage_state=self.context.storage_state())
        self.addCleanup(restored.close)
        page = restored.new_page()
        page.goto(ORIGIN + '/editor')
        self.assertEqual(page.locator('#auth').inner_text(), 'Authenticated fixture user')
        self.assertEqual(len(FixtureEditor(page).snapshot()), 1)
        with self.assertRaises(PrototypeError):
            FixtureEditor(page).create_draft(self.spec, self.ledger)
        self.assertEqual(len(editor.snapshot()), 1)

    def test_ambiguous_create_is_never_retried(self):
        editor = FixtureEditor(self.page)
        with self.assertRaises(PrototypeError):
            editor.create_draft(self.spec, self.ledger, fail_after_create=True)
        self.page.reload()
        with self.assertRaises(PrototypeError):
            FixtureEditor(self.page).create_draft(self.spec, self.ledger)
        self.assertEqual(len(editor.snapshot()), 1)

    def test_expired_or_missing_session_stops_before_claim(self):
        self.context.clear_cookies()
        self.page.reload()
        with self.assertRaises(PrototypeError):
            FixtureEditor(self.page).create_draft(self.spec, self.ledger)
        self.assertTrue(self.ledger.claim(self.spec))
        self.assertEqual(FixtureEditor(self.page).snapshot(), [])

    def test_wrong_origin_rejected(self):
        self.page.goto('about:blank')
        with self.assertRaises(PrototypeError):
            FixtureEditor(self.page)
