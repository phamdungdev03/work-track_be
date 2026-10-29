"""Regression checks for adopting an existing MySQL schema without modifying it."""
import importlib
from types import SimpleNamespace
from unittest.mock import patch

from django.db import connection
from django.test import TestCase

migration = importlib.import_module('attendance.migrations.0001_initial')


class MigrationBaselineTests(TestCase):
    def test_installed_schema_matches_frozen_baseline(self):
        migration.install_or_verify_schema(None, SimpleNamespace(connection=connection))

    def test_rejects_missing_index_in_existing_schema(self):
        with connection.cursor() as cursor:
            actual = migration.schema_records(cursor)
        actual['indexes'] = [row for row in actual['indexes'] if row[1] != 'uq_scan_qr_employee']
        with patch.object(migration, 'schema_records', return_value=actual):
            with self.assertRaisesRegex(RuntimeError, 'uq_scan_qr_employee'):
                migration.install_or_verify_schema(None, SimpleNamespace(connection=connection))

    def test_normalization_preserves_case_and_whitespace_inside_literals(self):
        normalize = migration.normalize_expression
        self.assertEqual(normalize("(`status` = _ascii\\'ACTIVE\\')"), normalize("(status = _utf8mb4\\'ACTIVE\\')"))
        self.assertNotEqual(normalize("status = 'ACTIVE'"), normalize("status = 'active'"))
        self.assertNotEqual(normalize("status = 'A B'"), normalize("status = 'AB'"))
