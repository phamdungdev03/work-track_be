"""Tests require an explicitly selected disposable MySQL instance/database."""
import os
from django.core.exceptions import ImproperlyConfigured
from .settings import *  # noqa: F403

if os.getenv('WORKTRACK_ALLOW_TEST_DB') != 'true':
    raise ImproperlyConfigured('Set WORKTRACK_ALLOW_TEST_DB=true and isolated DB_* before running MySQL tests.')
test_name = os.getenv('WORKTRACK_TEST_DB_NAME', 'test_worktrack_backend')
if not test_name.startswith('test_worktrack_') or not test_name.replace('_', '').isalnum():
    raise ImproperlyConfigured('Test database name must start with test_worktrack_ and contain only letters/digits/underscores.')
DATABASES['default']['NAME'] = test_name  # noqa: F405
DATABASES['default']['TEST'] = {'NAME': test_name}  # noqa: F405
DATABASES['default']['CONN_MAX_AGE'] = 0  # noqa: F405
TEST_RUNNER = 'attendance.test_runner.ExistingSchemaRunner'
DEMO_MODE = True
ALLOWED_HOSTS = ['testserver', 'localhost', '127.0.0.1']
