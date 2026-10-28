from pathlib import Path
import sqlparse
from django.conf import settings
from django.db import connection
from django.test.runner import DiscoverRunner


class ExistingSchemaRunner(DiscoverRunner):
    """Install actual DDL in Django's separate test database for unmanaged models."""
    def setup_databases(self, **kwargs):
        if not settings.DATABASES['default'].get('TEST', {}).get('NAME', '').startswith('test_worktrack_'):
            raise RuntimeError('Use --settings=config.test_settings with an isolated MySQL instance.')
        result = super().setup_databases(**kwargs)
        schema = Path(settings.BASE_DIR).parent / 'database' / 'attendance-schema.sql'
        with connection.cursor() as cursor:
            for statement in sqlparse.split(schema.read_text()):
                if statement.strip():
                    cursor.execute(statement)
        return result
