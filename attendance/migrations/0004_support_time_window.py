from django.db import migrations


def forward(apps, schema_editor):
    schema_editor.execute("ALTER TABLE support_assignments DROP CHECK ck_support_assignments_3, MODIFY COLUMN expected_arrival_at DATETIME(6) NULL, ADD CONSTRAINT ck_support_assignments_3 CHECK (depart_at < support_ends_at)")


def reverse(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('SELECT COUNT(*) FROM support_assignments WHERE expected_arrival_at IS NULL OR expected_arrival_at < depart_at OR expected_arrival_at >= support_ends_at')
        if cursor.fetchone()[0]:
            raise RuntimeError('Cannot reverse: some support assignments do not have a compatible expected arrival.')
    schema_editor.execute("ALTER TABLE support_assignments DROP CHECK ck_support_assignments_3, MODIFY COLUMN expected_arrival_at DATETIME(6) NOT NULL, ADD CONSTRAINT ck_support_assignments_3 CHECK (depart_at <= expected_arrival_at AND expected_arrival_at < support_ends_at)")


class Migration(migrations.Migration):
    atomic = False
    dependencies = [('attendance', '0003_demo_replace_event_requests')]
    operations = [migrations.RunPython(forward, reverse)]
