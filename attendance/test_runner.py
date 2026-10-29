from django.conf import settings
from django.test.runner import DiscoverRunner


class ExistingSchemaRunner(DiscoverRunner):
    """Allow tests only against explicitly selected disposable MySQL databases."""
    def setup_databases(self, **kwargs):
        if not settings.DATABASES['default'].get('TEST', {}).get('NAME', '').startswith('test_worktrack_'):
            raise RuntimeError('Use --settings=config.test_settings with an isolated MySQL instance.')
        return super().setup_databases(**kwargs)
