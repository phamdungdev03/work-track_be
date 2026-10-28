from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, DatabaseError


class Command(BaseCommand):
    help = 'Kiểm tra kết nối và sự tồn tại của 10 bảng, không ghi dữ liệu.'

    def handle(self, *args, **options):
        try:
            with connection.cursor() as cursor:
                tables = set(connection.introspection.table_names(cursor))
                expected = {model._meta.db_table for model in apps.get_app_config('attendance').get_models()}
                missing = expected - tables
                if missing:
                    raise CommandError('Thiếu bảng: ' + ', '.join(sorted(missing)))
        except DatabaseError:
            raise CommandError('Không kết nối được MySQL. Kiểm tra DB_HOST/PORT/NAME/USER/PASSWORD trong .env.')
        self.stdout.write(self.style.SUCCESS('Kết nối MySQL thành công; đã tìm thấy đủ 10 bảng.'))
