import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from vericomedia_publisher.__main__ import main
from vericomedia_publisher.ledger import Ledger
from vericomedia_publisher.planner import plan, scheduled_date


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.content = self.root / 'content'
        self.content.mkdir()
        self.article = dict(id='article-1', slug='article-1', title='Тест',
                            html='<p>Текст</p>', enabled=True)
        self.write()

    def write(self, name='article.json', **changes):
        (self.content / name).write_text(json.dumps(self.article | changes))

    def test_plan_is_deterministic_and_offline(self):
        with patch('socket.socket', side_effect=AssertionError('No network')):
            first = plan(self.content)
            self.assertEqual(first, plan(self.content))
        self.assertFalse(first['publishing_enabled'])
        self.assertEqual(len(first['articles']), 1)
        self.assertNotIn('html', first['articles'][0])

    def test_content_change_changes_digest(self):
        before = plan(self.content)['articles'][0]['sha256']
        self.write(html='<p>Changed</p>')
        self.assertNotEqual(before, plan(self.content)['articles'][0]['sha256'])

    def test_disabled_example_is_not_planned(self):
        self.write(enabled=False)
        self.assertEqual(plan(self.content)['articles'], [])

    def test_invalid_fields_and_slug(self):
        for field, value in [('id', ''), ('html', 1), ('slug', '../x'), ('enabled', 'false')]:
            with self.subTest(field=field):
                self.write(**{field: value})
                with self.assertRaises(ValueError):
                    plan(self.content)

    def test_duplicate_id_or_slug_rejected(self):
        for changes in [dict(slug='different'), dict(id='different')]:
            with self.subTest(changes=changes):
                self.write('second.json', **changes)
                with self.assertRaises(ValueError):
                    plan(self.content)

    def test_invalid_json_and_non_object(self):
        for value in ('{', '[]'):
            (self.content / 'article.json').write_text(value)
            self.assertEqual(main(['--content', str(self.content)]), 1)

    def test_missing_directory_is_error(self):
        self.assertEqual(main(['--content', str(self.root / 'absent')]), 1)

    def test_logs_do_not_expose_article_or_exception_text(self):
        with patch('vericomedia_publisher.__main__.plan', side_effect=ValueError('SECRET_TOKEN')):
            with self.assertLogs('vericomedia_publisher', level='ERROR') as logs:
                self.assertEqual(main([]), 1)
        self.assertNotIn('SECRET_TOKEN', str(logs.output))

    def test_publish_is_blocked_before_reading_content(self):
        with patch('vericomedia_publisher.__main__.plan') as planner:
            self.assertEqual(main(['--publish']), 2)
            planner.assert_not_called()

    def test_output_and_dry_run_does_not_create_ledger(self):
        output = self.root / 'out' / 'plan.json'
        self.assertEqual(main(['--content', str(self.content), '--output', str(output)]), 0)
        self.assertEqual(json.loads(output.read_text())['mode'], 'dry-run')
        self.assertEqual(list(self.root.rglob('*.sqlite3')), [])

    def test_scheduled_dates_and_year(self):
        for day in (1, 8):
            local = datetime(2026, 11, day, 10, tzinfo=ZoneInfo('Asia/Novosibirsk'))
            self.assertEqual(local.astimezone(timezone.utc).hour, 3)
            self.assertTrue(scheduled_date(local))
        for date in ('2027-11-01', '2026-10-01', '2026-11-02'):
            self.assertFalse(scheduled_date(datetime.fromisoformat(date).replace(tzinfo=timezone.utc)))
        with self.assertRaises(ValueError):
            scheduled_date(datetime(2026, 11, 1))

    def test_claim_survives_restart_and_changed_content(self):
        path = self.root / 'state.sqlite3'
        self.assertTrue(Ledger(path).claim('staging', 'a', 'v1'))
        self.assertFalse(Ledger(path).claim('staging', 'a', 'v1'))
        self.assertFalse(Ledger(path).claim('staging', 'a', 'v2'))
        self.assertTrue(Ledger(path).claim('other-target', 'a', 'v1'))

    def test_concurrent_claims_have_one_winner(self):
        ledger = Ledger(self.root / 'state.sqlite3')
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: ledger.claim('staging', 'a', 'hash'), range(16)))
        self.assertEqual(sum(results), 1)

    def test_only_matching_claim_can_complete(self):
        path = self.root / 'state.sqlite3'
        ledger = Ledger(path)
        ledger.claim('staging', 'a', 'v1')
        with self.assertRaises(ValueError):
            ledger.mark_published('staging', 'a', 'v2', 'remote-1')
        with self.assertRaises(ValueError):
            ledger.mark_published('staging', 'a', 'v1', '')
        ledger.mark_published('staging', 'a', 'v1', 'remote-1')
        self.assertFalse(ledger.claim('staging', 'a', 'v1'))
        with sqlite3.connect(path) as db:
            self.assertEqual(db.execute('SELECT status, remote_id FROM publications').fetchone(),
                             ('published', 'remote-1'))


if __name__ == '__main__':
    unittest.main()
