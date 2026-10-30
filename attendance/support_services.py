"""Support assignment writes for the no-login HR demo."""
import hashlib
import json
from datetime import datetime, timezone as utc

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from .exceptions import Conflict
from .models import AuditLog, Employee, Facility, SupportAssignment, WorkSchedule


def creation_hash(data):
    fields = {key: (value.astimezone(utc.utc).isoformat() if isinstance(value, datetime) else value)
              for key, value in data.items() if key != 'request_id'}
    return hashlib.sha256(json.dumps(fields, sort_keys=True, ensure_ascii=False).encode()).digest()


def snapshot(item):
    return {'schedule_id': item.schedule_id, 'from_facility_id': item.from_facility_id,
            'to_facility_id': item.to_facility_id, 'depart_at': item.depart_at.isoformat(),
            'expected_arrival_at': item.expected_arrival_at.isoformat() if item.expected_arrival_at else None,
            'support_ends_at': item.support_ends_at.isoformat(), 'status': item.status,
            'reason': item.reason, 'confirmed_by': item.confirmed_by_id,
            'confirmed_at': item.confirmed_at.isoformat() if item.confirmed_at else None, 'mode': 'HR_DEMO'}


def lock_schedule(schedule_id):
    ref = WorkSchedule.objects.filter(pk=schedule_id).values('employee_id').first()
    if ref is None:
        raise NotFound('Không tìm thấy ca làm. Hãy chọn ca đã phân cho nhân viên.')
    employee = Employee.objects.select_for_update().get(pk=ref['employee_id'])
    schedule = WorkSchedule.objects.select_for_update().get(pk=schedule_id)
    if schedule.employee_id != employee.id:
        raise Conflict('Ca đã thay đổi, hãy tải lại.')
    if employee.status != 'ACTIVE' or schedule.work_date < employee.hired_on or (employee.ended_on and schedule.work_date > employee.ended_on):
        raise ValidationError({'schedule_id': 'Nhân viên không hoạt động trong ngày của ca.'})
    if schedule.status != 'SCHEDULED':
        raise Conflict('Ca đã bị hủy, không thể thay đổi phân công.')
    if schedule.locked_at:
        raise Conflict('Ngày công đã khóa; cần mở lại trước khi thay đổi phân công.')
    return schedule


def validate_fields(schedule, data, *, exclude_id=None):
    facilities = {facility.id: facility for facility in Facility.objects.filter(pk__in=[data['from_facility_id'], data['to_facility_id']])}
    for field in ('from_facility_id', 'to_facility_id'):
        facility = facilities.get(data[field])
        if facility is None or not facility.is_active:
            raise ValidationError({field: 'Cơ sở không tồn tại hoặc đã ngừng hoạt động.'})
    if not schedule.starts_at <= data['depart_at'] < data['support_ends_at'] <= schedule.ends_at:
        raise ValidationError({'depart_at': 'Giờ bắt đầu và kết thúc support phải thuộc ca; giờ bắt đầu phải trước giờ kết thúc.'})
    overlaps = SupportAssignment.objects.filter(schedule=schedule, status__in=['PLANNED', 'CONFIRMED'],
        depart_at__lt=data['support_ends_at'], support_ends_at__gt=data['depart_at'])
    if exclude_id:
        overlaps = overlaps.exclude(pk=exclude_id)
    if overlaps.exists():
        raise Conflict('Thời gian phân công chồng với phân công khác của nhân viên trong ca.')


def create_assignment(data):
    digest = creation_hash(data)
    try:
        with transaction.atomic():
            existing = SupportAssignment.objects.filter(client_request_id=data['request_id']).first()
            if existing:
                if bytes(existing.creation_hash) != digest:
                    raise Conflict('Mã request đã dùng với nội dung khác.')
                return existing, True
            schedule = lock_schedule(data['schedule_id'])
            existing = SupportAssignment.objects.filter(client_request_id=data['request_id']).first()
            if existing:
                if bytes(existing.creation_hash) != digest:
                    raise Conflict('Mã request đã dùng với nội dung khác.')
                return existing, True
            validate_fields(schedule, data)
            item = SupportAssignment.objects.create(schedule=schedule, from_facility_id=data['from_facility_id'],
                to_facility_id=data['to_facility_id'], depart_at=data['depart_at'],
                expected_arrival_at=data.get('expected_arrival_at'), support_ends_at=data['support_ends_at'],
                reason=data['reason'], status='CONFIRMED', created_by=None, confirmed_by=None,
                confirmed_at=timezone.now(), client_request_id=data['request_id'], creation_hash=digest)
            AuditLog.objects.create(actor_type='SYSTEM', action='CREATE_SUPPORT_ASSIGNMENT',
                entity_type='support_assignments', entity_id=item.id, after_data=snapshot(item), reason=item.reason)
            return item, False
    except IntegrityError:
        item = SupportAssignment.objects.filter(client_request_id=data['request_id']).first()
        if item and bytes(item.creation_hash) == digest:
            return item, True
        if item:
            raise Conflict('Mã request đã dùng với nội dung khác.')
        raise


def lock_assignment(assignment_id):
    ref = SupportAssignment.objects.filter(pk=assignment_id).values('schedule_id').first()
    if ref is None:
        raise NotFound('Không tìm thấy phân công.')
    schedule = lock_schedule(ref['schedule_id'])
    item = SupportAssignment.objects.select_for_update().get(pk=assignment_id)
    if item.schedule_id != schedule.id:
        raise Conflict('Ca của phân công đã thay đổi, hãy tải lại.')
    return schedule, item


def check_version(item, expected):
    if item.updated_at != expected:
        raise Conflict('Phân công đã thay đổi. Hãy tải lại trước khi tiếp tục.')
    if item.status == 'CANCELLED':
        raise Conflict('Phân công đã hủy, không thể sửa hoặc hủy lại.')


@transaction.atomic
def update_assignment(assignment_id, data):
    schedule, item = lock_assignment(assignment_id)
    check_version(item, data['expected_updated_at'])
    validate_fields(schedule, data, exclude_id=item.id)
    before = snapshot(item)
    for field in ('from_facility_id', 'to_facility_id', 'depart_at', 'support_ends_at', 'reason'):
        setattr(item, field, data[field])
    fields = ['from_facility', 'to_facility', 'depart_at', 'support_ends_at', 'reason', 'updated_at']
    if 'expected_arrival_at' in data:
        item.expected_arrival_at = data['expected_arrival_at']
        fields.append('expected_arrival_at')
    if item.status == 'CONFIRMED':
        item.confirmed_by = None
        item.confirmed_at = timezone.now()
        fields += ['confirmed_by', 'confirmed_at']
    item.save(update_fields=fields)
    AuditLog.objects.create(actor_type='SYSTEM', action='UPDATE_SUPPORT_ASSIGNMENT',
        entity_type='support_assignments', entity_id=item.id, before_data=before, after_data=snapshot(item), reason=data['reason'])
    return item


@transaction.atomic
def cancel_assignment(assignment_id, data):
    _, item = lock_assignment(assignment_id)
    check_version(item, data['expected_updated_at'])
    before = snapshot(item)
    item.status = 'CANCELLED'
    item.save(update_fields=['status', 'updated_at'])
    AuditLog.objects.create(actor_type='SYSTEM', action='CANCEL_SUPPORT_ASSIGNMENT',
        entity_type='support_assignments', entity_id=item.id, before_data=before, after_data=snapshot(item), reason=data['reason'])
    return item


@transaction.atomic
def create_demo_schedule(employee_id, work_date, *, automatic=False):
    """Explicit opt-in: one default shift per employee/day, serialized by employee."""
    from datetime import time
    from zoneinfo import ZoneInfo
    try:
        employee = Employee.objects.select_for_update().get(pk=employee_id)
    except Employee.DoesNotExist:
        raise NotFound('Không tìm thấy nhân viên.')
    if employee.status != 'ACTIVE' or work_date < employee.hired_on or (employee.ended_on and work_date > employee.ended_on):
        raise ValidationError({'employee_id': 'Nhân viên không hoạt động trong ngày này.'})
    existing = WorkSchedule.objects.filter(employee=employee, work_date=work_date).first()
    if existing:
        if existing.status != 'SCHEDULED':
            raise Conflict('Ngày này đã có ca bị hủy. Không tự khôi phục hoặc tạo trùng ca.')
        return existing, True
    if not employee.home_facility.is_active:
        raise ValidationError({'employee_id': 'Cơ sở mặc định của nhân viên đã ngừng hoạt động.'})
    zone = ZoneInfo('Asia/Ho_Chi_Minh')
    item = WorkSchedule.objects.create(employee=employee, owner_facility_id=employee.home_facility_id,
        work_date=work_date, timezone='Asia/Ho_Chi_Minh',
        starts_at=datetime.combine(work_date, time(8, 30), tzinfo=zone),
        ends_at=datetime.combine(work_date, time(17, 30), tzinfo=zone),
        standard_work_minutes=480, unpaid_break_minutes=60, status='SCHEDULED', revision=1,
        policy_snapshot={'version':'demo-v1','break_start_local':'12:00','break_end_local':'13:00',
                         'break_confirmed':False,'rounding':'floor_minutes','automatic_ot':False,
                         'max_regular_minutes':480}, created_by=None)
    AuditLog.objects.create(actor_type='SYSTEM', action='CREATE_DEMO_SCHEDULE', entity_type='work_schedules',
        entity_id=item.id, after_data={'employee_id':employee_id,'work_date':work_date.isoformat(),
            'starts_at':item.starts_at.isoformat(),'ends_at':item.ends_at.isoformat(),
            'policy_snapshot':item.policy_snapshot,'mode':'AUTO_DEMO' if automatic else 'HR_DEMO'},
        reason='Tạo ca mặc định khi chấm công' if automatic else 'Tạo ca demo theo thao tác HR')
    return item, False


@transaction.atomic
def ensure_default_schedules(work_date):
    """Create today's or a future demo day's missing schedules, never alter existing ones."""
    from datetime import time
    from zoneinfo import ZoneInfo
    zone = ZoneInfo('Asia/Ho_Chi_Minh')
    if work_date < timezone.now().astimezone(zone).date():
        raise ValidationError({'work_date': 'Không tự tạo ca cho ngày đã qua.'})
    employees = list(Employee.objects.filter(status='ACTIVE', hired_on__lte=work_date,
        home_facility__is_active=True).filter(Q(ended_on__isnull=True) | Q(ended_on__gte=work_date))
        .order_by('id').select_for_update())
    existing = set(WorkSchedule.objects.filter(work_date=work_date,
        employee_id__in=[employee.id for employee in employees]).values_list('employee_id', flat=True))
    starts_at = datetime.combine(work_date, time(8, 30), tzinfo=zone)
    ends_at = datetime.combine(work_date, time(17, 30), tzinfo=zone)
    policy = {'version': 'demo-v1', 'break_start_local': '12:00', 'break_end_local': '13:00',
              'break_confirmed': False, 'rounding': 'floor_minutes', 'automatic_ot': False,
              'max_regular_minutes': 480}
    schedules = [WorkSchedule(employee=employee, owner_facility_id=employee.home_facility_id,
        work_date=work_date, timezone='Asia/Ho_Chi_Minh', starts_at=starts_at, ends_at=ends_at,
        standard_work_minutes=480, unpaid_break_minutes=60, status='SCHEDULED', revision=1,
        policy_snapshot=policy, created_by=None) for employee in employees if employee.id not in existing]
    WorkSchedule.objects.bulk_create(schedules)
    created_ids = dict(WorkSchedule.objects.filter(work_date=work_date,
        employee_id__in=[item.employee_id for item in schedules]).values_list('employee_id', 'id'))
    AuditLog.objects.bulk_create([AuditLog(actor_type='SYSTEM', action='CREATE_DEMO_SCHEDULE',
        entity_type='work_schedules', entity_id=created_ids[item.employee_id],
        after_data={'employee_id': item.employee_id, 'work_date': work_date.isoformat(),
                    'starts_at': starts_at.isoformat(), 'ends_at': ends_at.isoformat(),
                    'policy_snapshot': policy, 'mode': 'AUTO_DEMO'},
        reason='Tạo ca mặc định cho ngày demo') for item in schedules])
    return {'work_date': work_date, 'created': len(schedules), 'existing': len(existing)}
