"""Existing SQL tables: unmanaged; SQL owns constraints and generated columns."""
from django.db import models
from django.utils.timezone import now

class Facility(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=50)
    name = models.CharField(max_length=200)
    address = models.CharField(max_length=500, null=True)
    is_active = models.BooleanField(default=True)
    latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True)
    geofence_radius_m = models.PositiveIntegerField(null=True)
    qr_ttl_seconds = models.PositiveSmallIntegerField(default=20)
    max_location_age_seconds = models.PositiveIntegerField(null=True)
    max_location_accuracy_m = models.PositiveIntegerField(null=True)
    min_scan_interval_seconds = models.PositiveSmallIntegerField(default=10)
    policy_revision = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(default=now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'facilities'


class Employee(models.Model):
    id = models.BigAutoField(primary_key=True)
    employee_code = models.CharField(max_length=50)
    full_name = models.CharField(max_length=200)
    hired_on = models.DateField()
    ended_on = models.DateField(null=True)
    status = models.CharField(max_length=30, default='ACTIVE')
    created_at = models.DateTimeField(default=now)
    updated_at = models.DateTimeField(auto_now=True)
    home_facility = models.ForeignKey('Facility', on_delete=models.DO_NOTHING, db_column='home_facility_id', related_name='+')

    class Meta:
        managed = False
        db_table = 'employees'


class Account(models.Model):
    id = models.BigAutoField(primary_key=True)
    login_name = models.CharField(max_length=100)
    password_hash = models.CharField(max_length=255)
    role = models.CharField(max_length=30)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=now)
    updated_at = models.DateTimeField(auto_now=True)
    employee = models.ForeignKey('Employee', on_delete=models.DO_NOTHING, db_column='employee_id', related_name='+', null=True)

    class Meta:
        managed = False
        db_table = 'users'


class WorkSchedule(models.Model):
    id = models.BigAutoField(primary_key=True)
    employee = models.ForeignKey('Employee', on_delete=models.DO_NOTHING, db_column='employee_id', related_name='+')
    owner_facility = models.ForeignKey('Facility', on_delete=models.DO_NOTHING, db_column='owner_facility_id', related_name='+')
    work_date = models.DateField()
    timezone = models.CharField(max_length=64, default='Asia/Ho_Chi_Minh')
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    standard_work_minutes = models.PositiveSmallIntegerField(default=480)
    unpaid_break_minutes = models.PositiveSmallIntegerField(default=60)
    policy_snapshot = models.JSONField()
    status = models.CharField(max_length=20, default='SCHEDULED')
    revision = models.PositiveIntegerField(default=1)
    locked_at = models.DateTimeField(null=True)
    locked_by = models.ForeignKey('Account', on_delete=models.DO_NOTHING, db_column='locked_by', related_name='+', null=True)
    locked_result = models.JSONField(null=True)
    created_by = models.ForeignKey('Account', on_delete=models.DO_NOTHING, db_column='created_by', related_name='+', null=True)
    created_at = models.DateTimeField(default=now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'work_schedules'


class SupportAssignment(models.Model):
    id = models.BigAutoField(primary_key=True)
    depart_at = models.DateTimeField()
    expected_arrival_at = models.DateTimeField(null=True)
    support_ends_at = models.DateTimeField()
    status = models.CharField(max_length=30, default='PLANNED')
    reason = models.CharField(max_length=1000)
    confirmed_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(default=now)
    updated_at = models.DateTimeField(auto_now=True)
    schedule = models.ForeignKey('WorkSchedule', on_delete=models.DO_NOTHING, db_column='schedule_id', related_name='+')
    from_facility = models.ForeignKey('Facility', on_delete=models.DO_NOTHING, db_column='from_facility_id', related_name='+')
    to_facility = models.ForeignKey('Facility', on_delete=models.DO_NOTHING, db_column='to_facility_id', related_name='+')
    created_by = models.ForeignKey('Account', on_delete=models.DO_NOTHING, db_column='created_by', related_name='+', null=True)
    client_request_id = models.CharField(max_length=100, null=True)
    creation_hash = models.BinaryField(max_length=32, null=True)
    confirmed_by = models.ForeignKey('Account', on_delete=models.DO_NOTHING, db_column='confirmed_by', related_name='+', null=True)

    class Meta:
        managed = False
        db_table = 'support_assignments'


class QrChallenge(models.Model):
    id = models.BigAutoField(primary_key=True)
    nonce_hash = models.BinaryField(max_length=32)
    issued_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True)
    policy_snapshot = models.JSONField()
    created_at = models.DateTimeField(default=now)
    updated_at = models.DateTimeField(auto_now=True)
    facility = models.ForeignKey('Facility', on_delete=models.DO_NOTHING, db_column='facility_id', related_name='+')
    issued_by = models.ForeignKey('Account', on_delete=models.DO_NOTHING, db_column='issued_by', related_name='+', null=True)

    class Meta:
        managed = False
        db_table = 'qr_challenges'


class AttendanceAlert(models.Model):
    id = models.BigAutoField(primary_key=True)
    work_date = models.DateField()
    alert_type = models.CharField(max_length=80)
    status = models.CharField(max_length=30, default='OPEN')
    first_seen_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    verified_at = models.DateTimeField(null=True)
    review_note = models.CharField(max_length=1000, null=True)
    created_at = models.DateTimeField(default=now)
    updated_at = models.DateTimeField(auto_now=True)
    employee = models.ForeignKey('Employee', on_delete=models.DO_NOTHING, db_column='employee_id', related_name='+')
    facility = models.ForeignKey('Facility', on_delete=models.DO_NOTHING, db_column='facility_id', related_name='+')
    verified_by = models.ForeignKey('Account', on_delete=models.DO_NOTHING, db_column='verified_by', related_name='+', null=True)

    class Meta:
        managed = False
        db_table = 'attendance_alerts'


class AttendanceScan(models.Model):
    id = models.BigAutoField(primary_key=True)
    employee = models.ForeignKey('Employee', on_delete=models.DO_NOTHING, db_column='employee_id', related_name='+', null=True)
    facility = models.ForeignKey('Facility', on_delete=models.DO_NOTHING, db_column='facility_id', related_name='+')
    actor_user = models.ForeignKey('Account', on_delete=models.DO_NOTHING, db_column='actor_user_id', related_name='+', null=True)
    source_type = models.CharField(max_length=20)
    source_key = models.CharField(max_length=100)
    source_event_id = models.CharField(max_length=100)
    payload_hash = models.BinaryField(max_length=32)
    occurred_at = models.DateTimeField()
    received_at = models.DateTimeField()
    outcome = models.CharField(max_length=20)
    event_type = models.CharField(max_length=3, null=True)
    reason_code = models.CharField(max_length=80)
    decision_snapshot = models.JSONField()
    latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True)
    accuracy_m = models.DecimalField(max_digits=10, decimal_places=2, null=True)
    location_observed_at = models.DateTimeField(null=True)
    qr_challenge = models.ForeignKey('QrChallenge', on_delete=models.DO_NOTHING, db_column='qr_challenge_id', related_name='+', null=True)
    alert = models.ForeignKey('AttendanceAlert', on_delete=models.DO_NOTHING, db_column='alert_id', related_name='+', null=True)
    created_at = models.DateTimeField(default=now)

    class Meta:
        managed = False
        db_table = 'attendance_scans'


class AttendanceRequest(models.Model):
    id = models.BigAutoField(primary_key=True)
    client_request_id = models.CharField(max_length=100, null=True)
    employee = models.ForeignKey('Employee', on_delete=models.DO_NOTHING, db_column='employee_id', related_name='+')
    schedule = models.ForeignKey('WorkSchedule', on_delete=models.DO_NOTHING, db_column='schedule_id', related_name='+', null=True)
    requested_by = models.ForeignKey('Account', on_delete=models.DO_NOTHING, db_column='requested_by', related_name='+', null=True)
    request_type = models.CharField(max_length=20)
    target_scan = models.ForeignKey('AttendanceScan', on_delete=models.DO_NOTHING, db_column='target_scan_id', related_name='+', null=True)
    origin_scan = models.ForeignKey('AttendanceScan', on_delete=models.DO_NOTHING, db_column='origin_scan_id', related_name='+', null=True)
    proposed_event_type = models.CharField(max_length=3, null=True)
    proposed_facility = models.ForeignKey('Facility', on_delete=models.DO_NOTHING, db_column='proposed_facility_id', related_name='+', null=True)
    proposed_occurred_at = models.DateTimeField(null=True)
    reason = models.CharField(max_length=1000)
    status = models.CharField(max_length=20, default='PENDING')
    reviewed_by = models.ForeignKey('Account', on_delete=models.DO_NOTHING, db_column='reviewed_by', related_name='+', null=True)
    reviewed_at = models.DateTimeField(null=True)
    review_note = models.CharField(max_length=1000, null=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(default=now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'attendance_requests'


class AuditLog(models.Model):
    id = models.BigAutoField(primary_key=True)
    actor_type = models.CharField(max_length=30)
    action = models.CharField(max_length=50)
    entity_type = models.CharField(max_length=50)
    entity_id = models.PositiveBigIntegerField()
    before_data = models.JSONField(null=True)
    after_data = models.JSONField(null=True)
    reason = models.CharField(max_length=1000, null=True)
    created_at = models.DateTimeField(default=now)
    actor_user = models.ForeignKey('Account', on_delete=models.DO_NOTHING, db_column='actor_user_id', related_name='+', null=True)

    class Meta:
        managed = False
        db_table = 'audit_logs'

