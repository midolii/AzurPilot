"""验证 Janus 行动力统计在统一存储迁移后仍保留原口径。"""

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from module.log_res.log_res import LogRes
from module.statistics import resource_stats
from tests.opsi_test_support import install_store


class TestResourceStorageCompatibility(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        install_store(self, self.root)
        self.legacy_path = self.root / 'config' / 'azurstats_local.db'
        self.enterContext(patch.object(resource_stats, '_LOCAL_DB', str(self.legacy_path)))

    def test_legacy_payload_and_action_point_total_migrate_without_data_loss(self):
        with closing(sqlite3.connect(self.legacy_path)) as conn, conn:
            conn.execute('''CREATE TABLE resource_snapshots (
                id INTEGER PRIMARY KEY, instance TEXT, ts TEXT,
                action_point INTEGER, action_point_total INTEGER,
                yellow_coin INTEGER, purple_coin INTEGER, opsi_payload TEXT)''')
            conn.execute('INSERT INTO resource_snapshots VALUES(1, ?, ?, NULL, 1800, NULL, NULL, ?)',
                         ('alas', '2026-10-01T12:00:00', json.dumps({
                             'action_point': 200, 'yellow_coin': 10, 'purple_coin': 20})))
        original = self.legacy_path.read_bytes()

        rows = resource_stats.get_resource_timeline('alas')

        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['action_point'], rows[0]['action_point_total'],
                          rows[0]['yellow_coin'], rows[0]['purple_coin']), (200, 1800, 10, 20))
        self.assertEqual(original, self.legacy_path.read_bytes())
        self.assertTrue((self.root / 'config' / 'azurpilot.migrated').is_file())

    def test_existing_upstream_database_adds_total_column_without_losing_rows(self):
        database = resource_stats._database()
        database.ensure_ready()
        with database.transaction() as conn:
            conn.execute('ALTER TABLE resource_snapshots DROP COLUMN action_point_total')
            conn.execute("INSERT INTO storage_instances VALUES('alas')")
            conn.execute("INSERT INTO resource_snapshots(instance, ts, oil) VALUES('alas', '2026-10-01', 1234)")

        self.assertTrue(resource_stats.record_resource_snapshot('alas', {
            'ActionPoint': 200, 'ActionPointTotal': 1800}))
        rows = resource_stats.get_resource_timeline('alas')

        self.assertEqual(rows[0]['oil'], 1234)
        self.assertIsNone(rows[0]['action_point_total'])
        self.assertEqual(rows[1]['action_point_total'], 1800)
        with database.transaction(write=False) as conn:
            self.assertEqual(conn.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(conn.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_async_snapshot_preserves_sampling_time_and_copies_total_value(self):
        resources = {'ActionPoint': 200, 'ActionPointTotal': 1800}
        stamp = datetime(2026, 10, 1, 12, 30)
        future = resource_stats.async_record_resource_snapshot('alas', resources, observed_at=stamp)
        resources['ActionPointTotal'] = 9999

        self.assertTrue(future.result(timeout=15))
        row = resource_stats.get_resource_timeline('alas')[0]

        self.assertEqual(row['ts'], stamp.isoformat())
        self.assertEqual(row['action_point_total'], 1800)

    def test_log_resource_keeps_total_when_using_deferred_history(self):
        config = SimpleNamespace(config_name='alas', modified={'Dashboard.ActionPoint.Total': 1800},
                                 data={'Dashboard': {'ActionPoint': {'Value': 200, 'Total': 1000}}})
        recorder = LogRes(config)
        recorder.__dict__['groups'] = ['ActionPoint']
        recorder.__dict__['_defer_history'] = True
        stamp = datetime(2026, 10, 1, 12, 30)
        recorder.__dict__['_recorded_at'] = stamp

        with patch.object(resource_stats, 'async_record_resource_snapshot') as record_async, \
                patch.object(resource_stats, 'record_resource_snapshot') as record_sync:
            recorder._record_all_resource_snapshot()

        record_async.assert_called_once_with('alas', {'ActionPoint': 200, 'ActionPointTotal': 1800},
                                             observed_at=stamp)
        record_sync.assert_not_called()
