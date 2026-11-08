"""Regression tests for bill calculations and missing-data safeguards."""
import importlib.util
import asyncio
from datetime import date
from unittest.mock import patch, AsyncMock
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import sys
from unittest.mock import MagicMock

try:
    import aiohttp
except ModuleNotFoundError:
    sys.modules["aiohttp"] = MagicMock()

ENGINE_PATH = Path(__file__).resolve().parents[1] / 'custom_components' / 'jk51_billing' / 'engine.py'
spec = importlib.util.spec_from_file_location('jk51_engine_test', ENGINE_PATH)
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)


class BillingEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.old = (engine.CFG, engine.DB, engine.REPORTS)
        self.addCleanup(self.restore)
        root = Path(self.temp.name)
        engine.DB = root / 'ledger.sqlite3'
        engine.REPORTS = root / 'reports'
        engine.CFG = {'language': 'en', 'day_transfer_eur_per_kwh': '0.05',
                      'night_transfer_eur_per_kwh': '0.03', 'monthly_fee_eur': '5',
                      'monthly_peak_eur_per_kw': '2', 'electricity_margin_eur_per_kwh': '0.01',
                      'spot_vat_multiplier': '1'}
        self.start = datetime(2026, 1, 1, 7, tzinfo=timezone.utc)

    def restore(self):
        engine.CFG, engine.DB, engine.REPORTS = self.old

    def test_report_includes_fees_and_excludes_missing_hour(self):
        db = engine.database()
        for offset, energy, price, status in [(0, '2', '0.1', 'complete'), (1, None, '0.2', 'missing_energy')]:
            start = self.start + timedelta(hours=offset)
            db.execute('INSERT INTO hours VALUES (?,?,?,?,?)',
                       (start.isoformat(), (start + timedelta(hours=1)).isoformat(), energy, price, status))
        db.commit(); db.close()
        db, _, csv_path, body = engine.build_report(self.start, self.start + timedelta(hours=2), 'sample')
        db.close()
        # 0.20 spot + 0.02 margin + 0.10 day transfer + 5 fixed + 4 peak.
        self.assertIn('9.32', body)
        self.assertIn('missing_energy', csv_path.read_text())
        self.assertIn('2.000 kWh', body)

    def test_no_billable_hours_blocks_report(self):
        with self.assertRaisesRegex(RuntimeError, 'No billable hours'):
            engine.build_report(self.start, self.start + timedelta(hours=1), 'empty')
        self.assertFalse(engine.REPORTS.exists())

    def test_partial_month_sends_when_one_hour_has_both_statistics(self):
        start = datetime(2026, 10, 31, 22, tzinfo=timezone.utc)
        end = start + timedelta(hours=24)
        stamp = int(start.timestamp() * 1000)
        engine.CFG.update(energy_entity='sensor.energy', nordpool_entity='sensor.spot',
                          test_recipient=['test@example.com'])
        stats = {'sensor.energy': [{'start': stamp, 'change': 2}],
                 'sensor.spot': [{'start': stamp, 'mean': 0.1}]}
        with patch.object(engine, 'parse_test_period', return_value=(start, end)), \
             patch.object(engine, 'require_config'), \
             patch.object(engine, 'statistics', new_callable=AsyncMock, return_value=stats), \
             patch.object(engine, 'send_email') as send:
            asyncio.run(engine.manual_test_report('monthly', '2026-11'))
        self.assertEqual(send.call_count, 1)
        self.assertIn('1/24 hours billed', send.call_args.args[1])
        self.assertIn('unavailable for 23 hours', send.call_args.args[1])
        self.assertEqual(send.call_args.args[3], ['test@example.com'])

    def test_no_billable_hours_identifies_missing_statistics(self):
        engine.CFG.update(energy_entity='sensor.energy', nordpool_entity='sensor.spot')
        db = engine.database()
        db.execute('INSERT INTO hours VALUES (?,?,?,?,?)',
                   (self.start.isoformat(), (self.start + timedelta(hours=1)).isoformat(),
                    '2', None, 'missing_price'))
        db.commit(); db.close()
        with self.assertRaises(RuntimeError) as result:
            engine.build_report(self.start, self.start + timedelta(hours=2), 'test')
        self.assertIn('sensor.energy) missing or invalid for 1/2 hours', str(result.exception))
        self.assertIn('sensor.spot) missing or invalid for 2/2 hours', str(result.exception))
        self.assertNotIn('TEST-MANUAL', str(result.exception))

    def test_sent_quarter_is_not_reissued(self):
        db = engine.database()
        db.execute('INSERT INTO sent VALUES (?,?)', ('2026-Q1', self.start.isoformat()))
        db.commit(); db.close()
        with self.assertRaisesRegex(RuntimeError, 'already marked sent'):
            engine.build_report(self.start, self.start + timedelta(hours=1), '2026-Q1')

    def test_previous_periods_across_boundaries(self):
        start, end, ident = engine.previous_period('quarterly', date(2026, 1, 1))
        self.assertEqual((str(start.date()), str(end.date()), ident), ('2025-10-01', '2026-01-01', '2025-Q4'))
        start, end, ident = engine.previous_period('monthly', date(2026, 1, 1))
        self.assertEqual((str(start.date()), str(end.date()), ident), ('2025-12-01', '2026-01-01', '2025-12'))
        with self.assertRaises(RuntimeError):
            engine.previous_period('monthly', date(2026, 1, 2))

    def test_test_cc_isolated_from_production(self):
        engine.CFG.update(gmail_user="sender@example.com", gmail_app_password="secret",
                          cc=["production@example.com"], test_cc=["test-cc@example.com"])
        attachment = Path(self.temp.name) / "report.csv"
        attachment.write_text("example")
        with patch.object(engine.smtplib, "SMTP") as smtp:
            engine.send_email("test", "body", attachment, ["test@example.com"], is_test=True)
            message = smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
        self.assertEqual(message["To"], "test@example.com")
        self.assertEqual(message["Cc"], "test-cc@example.com")
        self.assertNotIn("production@example.com", str(message))

    def test_scheduled_monthly_report_sends_once(self):
        end = self.start + timedelta(hours=1)
        db = engine.database()
        db.execute('INSERT INTO hours VALUES (?,?,?,?,?)',
                   (self.start.isoformat(), end.isoformat(), '2', '0.1', 'complete'))
        db.commit(); db.close()
        engine.CFG['recipient'] = ['billing@example.com']
        with patch.object(engine, 'previous_period', return_value=(self.start, end, '2026-01')), \
             patch.object(engine, 'require_config'), \
             patch.object(engine, 'collect', new_callable=AsyncMock), \
             patch.object(engine, 'send_email') as send:
            asyncio.run(engine.scheduled_report('monthly', False))
            asyncio.run(engine.scheduled_report('monthly', False))
        self.assertEqual(send.call_count, 1)
        self.assertIn('9.32', send.call_args.args[1])

    def test_manual_period_selection_and_dst(self):
        now = datetime(2026, 11, 8, 12, 36, tzinfo=timezone.utc)
        for period, value, first, last in [
            ('monthly', '2026-02', '2026-02-01', '2026-03-01'),
            ('quarterly', '2025-Q4', '2025-10-01', '2026-01-01'),
        ]:
            with self.subTest(period=period):
                start, end = engine.parse_test_period(period, value, now)
                self.assertEqual(str(start.astimezone(engine.LOCAL).date()), first)
                self.assertEqual(str(end.astimezone(engine.LOCAL).date()), last)
        for period, value in [('monthly', '2026-11'), ('quarterly', '2026-Q4')]:
            start, end = engine.parse_test_period(period, value, now)
            self.assertEqual(end, datetime(2026, 11, 8, 12, tzinfo=timezone.utc))
        start, end = engine.parse_test_period('monthly', '2026-03', now)
        self.assertEqual((end - start).total_seconds(), (31 * 24 - 1) * 3600)
        for period, value in [('monthly', '2026-13'), ('quarterly', '2026-Q5'),
                              ('monthly', '2026-12'), ('quarterly', '2027-Q1')]:
            with self.subTest(period=period, value=value), self.assertRaises(ValueError):
                engine.parse_test_period(period, value, now)

    def test_manual_report_uses_test_recipients_and_preserves_sent_history(self):
        end = self.start + timedelta(days=1)
        db = engine.database()
        db.execute('INSERT INTO hours VALUES (?,?,?,?,?)',
                   (self.start.isoformat(), (self.start + timedelta(hours=1)).isoformat(), '2', '0.1', 'complete'))
        db.commit(); db.close()
        engine.CFG.update(test_recipient=['test@example.com'], test_cc=['testcc@example.com'],
                          recipient=['production@example.com'], cc=['productioncc@example.com'])
        with patch.object(engine, 'parse_test_period', return_value=(self.start, end)), \
             patch.object(engine, 'require_config'), \
             patch.object(engine, 'collect', new_callable=AsyncMock) as collect, \
             patch.object(engine, 'send_email') as send:
            asyncio.run(engine.manual_test_report('monthly', '2026-01'))
            asyncio.run(engine.manual_test_report('monthly', '2026-01'))
        self.assertEqual(send.call_count, 2)
        collect.assert_awaited_with(self.start, end)
        self.assertEqual(send.call_args.args[3], ['test@example.com'])
        self.assertTrue(send.call_args.kwargs['is_test'])
        self.assertEqual(send.call_args.kwargs['subject_identifier'], '2026-01')
        self.assertIn('2026-01-01', send.call_args.args[1])
        self.assertIn('9.32', send.call_args.args[1])
        db = engine.database()
        try:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM sent').fetchone()[0], 0)
        finally:
            db.close()

    def test_monthly_and_quarterly_manual_tests_include_monthly_fees(self):
        end = self.start + timedelta(days=1)
        db = engine.database()
        db.execute('INSERT INTO hours VALUES (?,?,?,?,?)',
                   (self.start.isoformat(), (self.start + timedelta(hours=1)).isoformat(), '2', '0.1', 'complete'))
        db.commit(); db.close()
        engine.CFG['test_recipient'] = ['test@example.com']
        with patch.object(engine, 'parse_test_period', return_value=(self.start, end)), \
             patch.object(engine, 'require_config'), \
             patch.object(engine, 'collect', new_callable=AsyncMock), \
             patch.object(engine, 'send_email') as send:
            for period in ('monthly', 'quarterly'):
                asyncio.run(engine.manual_test_report(period, 'unused'))
                self.assertIn('9.32', send.call_args.args[1])


if __name__ == '__main__':
    unittest.main()
