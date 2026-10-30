"""Regression checks for adopting an existing MySQL schema without modifying it."""
import importlib
import json
from types import SimpleNamespace
from unittest.mock import patch

from django.db import connection
from django.test import TestCase

migration = importlib.import_module('attendance.migrations.0001_initial')


class MigrationBaselineTests(TestCase):
    def baseline_compatible_records(self):
        with connection.cursor() as cursor:
            records = migration.schema_records(cursor)
        checks = [row for row in records['checks'] if row[1] == 'ck_request_requester']
        self.assertEqual(len(checks), 1)
        self.assertIn('ADD_EVENT', checks[0][2])
        self.assertTrue(any(row[1] == 'client_request_id' for row in records['columns'] if row[0] == 'attendance_requests'))
        self.assertTrue(any(row[1] == 'uq_attendance_request_client_id' for row in records['indexes']))
        baseline = json.loads((migration.SCHEMA_DIR / '0001_manifest.json').read_text())
        replaced_checks = {'ck_request_requester', 'ck_support_assignments_3'}
        for old_check in baseline['checks']:
            if old_check[1] in replaced_checks:
                old_check[2] = migration.normalize_expression(old_check[2])
                records['checks'] = [row for row in records['checks'] if row[1] != old_check[1]] + [old_check]
        original_arrival = next(row for row in baseline['columns'] if row[0] == 'support_assignments' and row[1] == 'expected_arrival_at')
        records['columns'] = [row for row in records['columns'] if not (row[0] == 'support_assignments' and row[1] == 'expected_arrival_at')] + [original_arrival]
        return records

    def test_installed_schema_matches_frozen_baseline(self):
        actual = self.baseline_compatible_records()
        with patch.object(migration, 'schema_records', return_value=actual):
            migration.install_or_verify_schema(None, SimpleNamespace(connection=connection))

    def test_rejects_missing_index_in_existing_schema(self):
        actual = self.baseline_compatible_records()
        actual['indexes'] = [row for row in actual['indexes'] if row[1] != 'uq_scan_qr_employee']
        with patch.object(migration, 'schema_records', return_value=actual):
            with self.assertRaisesRegex(RuntimeError, 'uq_scan_qr_employee'):
                migration.install_or_verify_schema(None, SimpleNamespace(connection=connection))

    def test_normalization_preserves_case_and_whitespace_inside_literals(self):
        normalize = migration.normalize_expression
        self.assertEqual(normalize("(`status` = _ascii\\'ACTIVE\\')"), normalize("(status = _utf8mb4\\'ACTIVE\\')"))
        self.assertNotEqual(normalize("status = 'ACTIVE'"), normalize("status = 'active'"))
        self.assertNotEqual(normalize("status = 'A B'"), normalize("status = 'AB'"))
