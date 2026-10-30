from django.db import migrations


def change_constraint(apps, schema_editor):
    if schema_editor.connection.vendor != 'mysql':
        raise RuntimeError('WorkTrack requires MySQL.')
    schema_editor.execute("ALTER TABLE attendance_requests ADD COLUMN client_request_id VARCHAR(100) NULL, ADD UNIQUE KEY uq_attendance_request_client_id (client_request_id), DROP CHECK ck_request_requester, ADD CONSTRAINT ck_request_requester CHECK (request_type IN ('PRESENCE', 'ADD_EVENT') OR requested_by IS NOT NULL)")


def restore_constraint(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM attendance_requests WHERE request_type = 'ADD_EVENT' AND requested_by IS NULL")
        if cursor.fetchone()[0]:
            raise RuntimeError('Cannot reverse: demo requests without a requester exist.')
    schema_editor.execute("ALTER TABLE attendance_requests DROP CHECK ck_request_requester, ADD CONSTRAINT ck_request_requester CHECK (request_type = 'PRESENCE' OR requested_by IS NOT NULL), DROP INDEX uq_attendance_request_client_id, DROP COLUMN client_request_id")


class Migration(migrations.Migration):
    atomic = False
    dependencies = [('attendance', '0001_initial')]
    operations = [migrations.RunPython(change_constraint, restore_constraint)]
