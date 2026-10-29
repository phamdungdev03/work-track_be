import re
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from attendance.models import Employee, Facility


class Command(BaseCommand):
    help = 'Nhập dữ liệu mẫu từ attendance-seed.sql vào database nếu database chưa có nhân viên.'

    def handle(self, *args, **options):
        if Employee.objects.exists():
            self.stdout.write(self.style.WARNING('Database đã có dữ liệu nhân viên, bỏ qua seed.'))
            return

        seed_file = Path(settings.BASE_DIR) / 'Database' / 'attendance-seed.sql'
        if not seed_file.exists():
            raise CommandError(f'Không tìm thấy file seed tại {seed_file}')

        self.stdout.write('Đang đọc file attendance-seed.sql...')
        content = seed_file.read_text(encoding='utf-8')
        statements = re.findall(r'INSERT INTO .*?;(?=\n)', content, re.S)

        if not statements:
            raise CommandError('Không tìm thấy câu lệnh INSERT nào trong file seed.')

        self.stdout.write(f'Tìm thấy {len(statements)} câu lệnh INSERT. Đang nhập dữ liệu...')
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    for idx, stmt in enumerate(statements, 1):
                        cursor.execute(stmt)
                        if idx % 50 == 0 or idx == len(statements):
                            self.stdout.write(f'Đã nạp {idx}/{len(statements)} câu lệnh...')
        except Exception as e:
            raise CommandError(f'Lỗi khi nạp dữ liệu: {e}')

        self.stdout.write(self.style.SUCCESS('Nạp dữ liệu seed thành công!'))
