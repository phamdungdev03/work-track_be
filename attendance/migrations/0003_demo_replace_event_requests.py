from django.db import migrations


def forward(apps, schema_editor):
    schema_editor.execute("ALTER TABLE attendance_requests DROP CHECK ck_request_requester, ADD CONSTRAINT ck_request_requester CHECK (request_type IN ('PRESENCE', 'ADD_EVENT', 'REPLACE_EVENT') OR requested_by IS NOT NULL)")


def reverse(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM attendance_requests WHERE request_type = 'REPLACE_EVENT' AND requested_by IS NULL")
        if cursor.fetchone()[0]:
            raise RuntimeError('Cannot reverse: demo replacement requests without a requester exist.')
    schema_editor.execute("ALTER TABLE attendance_requests DROP CHECK ck_request_requester, ADD CONSTRAINT ck_request_requester CHECK (request_type IN ('PRESENCE', 'ADD_EVENT') OR requested_by IS NOT NULL)")


class Migration(migrations.Migration):
    atomic = False
    dependencies = [('attendance', '0002_demo_add_event_requests')]
    operations = [migrations.RunPython(forward, reverse)]
