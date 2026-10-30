"""Demo scans only. Real devices and QR require their own authenticated adapters."""
import hashlib
import json
import secrets
from datetime import datetime, time, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo
from django.db import IntegrityError, OperationalError, transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError
from .exceptions import Conflict
from .models import (Employee, Facility, AttendanceScan, WorkSchedule,
                     AttendanceRequest, SupportAssignment, AttendanceAlert, AuditLog, QrChallenge)

BUSINESS_TZ = ZoneInfo('Asia/Ho_Chi_Minh')


def day_bounds(day):
    start = datetime.combine(day, time.min, tzinfo=BUSINESS_TZ)
    return start, start + timedelta(days=1)


def effective_events(employee_id, day):
    start, end = day_bounds(day)
    scans = AttendanceScan.objects.filter(employee_id=employee_id, outcome='ACCEPTED',
                                         occurred_at__gte=start, occurred_at__lt=end)
    events = {('scan', s.id): {'time': s.occurred_at, 'type': s.event_type,
                             'facility_id': s.facility_id, 'ref': f'scan:{s.id}'} for s in scans}
    corrections = AttendanceRequest.objects.filter(employee_id=employee_id, status='APPROVED').filter(
        Q(schedule__work_date=day) | Q(schedule__isnull=True, request_type='PRESENCE',
            proposed_occurred_at__gte=start, proposed_occurred_at__lt=end)).order_by('id')
    for request in corrections:
        if request.target_scan_id:
            events.pop(('scan', request.target_scan_id), None)
        if request.request_type != 'VOID_EVENT' and start <= request.proposed_occurred_at < end:
            events[('request', request.id)] = {'time': request.proposed_occurred_at,
                'type': request.proposed_event_type, 'facility_id': request.proposed_facility_id,
                'ref': f'request:{request.id}'}
    return sorted(events.values(), key=lambda event: (event['time'], event['ref']))


def payload_digest(data):
    normalized = dict(data)
    if 'occurred_at' in normalized:
        normalized['occurred_at'] = normalized['occurred_at'].astimezone(dt_timezone.utc).isoformat()
    return hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).digest()


def replay(existing, digest):
    if bytes(existing.payload_hash) != digest:
        raise Conflict()
    return existing, True


def issue_qr(facility_id, previous_token=None):
    """Issue a local-demo challenge. Only its hash is stored in MySQL."""
    try:
        facility = Facility.objects.get(pk=facility_id, is_active=True)
    except Facility.DoesNotExist:
        raise NotFound('Không tìm thấy cơ sở đang hoạt động.')
    token = secrets.token_urlsafe(32)
    now = timezone.now()
    with transaction.atomic():
        if previous_token:
            previous_hash = hashlib.sha256(previous_token.encode('utf-8')).digest()
            QrChallenge.objects.filter(facility=facility, nonce_hash=previous_hash,
                revoked_at__isnull=True).update(revoked_at=now)
        qr = QrChallenge.objects.create(facility=facility, nonce_hash=hashlib.sha256(token.encode('utf-8')).digest(),
            issued_at=now, expires_at=now + timedelta(seconds=facility.qr_ttl_seconds),
            policy_snapshot={'ttl_seconds': facility.qr_ttl_seconds, 'facility_policy_revision': facility.policy_revision, 'mode': 'DEMO'})
    return {'token': token, 'facility_id': facility.id, 'issued_at': qr.issued_at,
            'expires_at': qr.expires_at, 'server_now': timezone.now()}


def record_demo_scan(data, channel='FACE'):
    source_key = 'demo:kiosk' if channel == 'FACE' else 'demo:mobile-qr'
    digest = payload_digest(data)
    for attempt in range(3):
        try:
            return _record(data, source_key, digest, channel)
        except IntegrityError:
            existing = AttendanceScan.objects.filter(source_key=source_key, source_event_id=data['request_id']).first()
            if existing:
                return replay(existing, digest)
            raise
        except OperationalError as exc:
            if not exc.args or exc.args[0] not in (1205, 1213) or attempt == 2:
                raise
    raise RuntimeError('Unreachable')


@transaction.atomic
def create_add_event_request(data):
    employee = Employee.objects.select_for_update().filter(pk=data['employee_id']).first()
    if not employee:
        raise NotFound('Không tìm thấy nhân viên.')
    existing = AttendanceRequest.objects.filter(client_request_id=data['request_id']).first()
    if existing:
        same = (existing.employee_id == employee.id and existing.schedule and existing.schedule.work_date == data['date']
                and existing.proposed_facility_id == data['facility_id'] and existing.proposed_event_type == data['event_type']
                and existing.proposed_occurred_at == data['occurred_at'] and existing.reason == data['reason']
                and existing.target_scan_id == data.get('target_scan_id'))
        if not same:
            raise Conflict('Mã yêu cầu đã được dùng với nội dung khác.')
        return existing, True
    schedule = WorkSchedule.objects.select_for_update().filter(employee=employee, work_date=data['date'], status='SCHEDULED').first()
    if not schedule:
        raise ValidationError('Nhân viên chưa có ca làm việc trong ngày.')
    if schedule.locked_at:
        raise Conflict('Ngày công đã khóa. Cần mở lại trước khi giải trình.')
    if data['occurred_at'].astimezone(BUSINESS_TZ).date() != data['date']:
        raise ValidationError('Giờ đề xuất phải thuộc ngày làm việc.')
    if not Facility.objects.filter(pk=data['facility_id'], is_active=True).exists():
        raise ValidationError('Cơ sở không tồn tại hoặc đã ngừng hoạt động.')
    target = None
    if data.get('target_scan_id'):
        target = AttendanceScan.objects.filter(pk=data['target_scan_id'], employee=employee, outcome='ACCEPTED').first()
        if not target or target.occurred_at.astimezone(BUSINESS_TZ).date() != data['date']:
            raise ValidationError('Lượt cần sửa không hợp lệ hoặc không thuộc nhân viên và ngày đã chọn.')
        if AttendanceRequest.objects.filter(target_scan=target, status='APPROVED').exists():
            raise Conflict('Lượt này đã có điều chỉnh được duyệt.')
        if AttendanceRequest.objects.filter(target_scan=target, status='PENDING').exists():
            raise Conflict('Lượt này đã có yêu cầu đang chờ duyệt.')
    request_type = 'REPLACE_EVENT' if target else 'ADD_EVENT'
    if AttendanceRequest.objects.filter(employee=employee, schedule=schedule, request_type=request_type, status='PENDING',
            proposed_event_type=data['event_type'], proposed_occurred_at=data['occurred_at'], proposed_facility_id=data['facility_id']).exists():
        raise Conflict('Đã có yêu cầu bổ sung lượt này đang chờ duyệt.')
    item = AttendanceRequest.objects.create(client_request_id=data['request_id'], employee=employee, schedule=schedule,
        request_type=request_type, target_scan=target, proposed_event_type=data['event_type'], proposed_occurred_at=data['occurred_at'],
        proposed_facility_id=data['facility_id'], reason=data['reason'], status='PENDING')
    AuditLog.objects.create(actor_type='SYSTEM', action='CREATE_ATTENDANCE_REQUEST', entity_type='attendance_requests',
        entity_id=item.id, after_data={'mode': 'DEMO', 'request_type': request_type}, reason=data['reason'])
    return item, False


@transaction.atomic
def _record(data, source_key, digest, channel):
    # A stable employee row also serializes concurrent FIRST scans with no history.
    try:
        employee = Employee.objects.select_for_update().get(pk=data['employee_id'])
    except Employee.DoesNotExist:
        raise NotFound('Không tìm thấy nhân viên.')
    existing = AttendanceScan.objects.filter(source_key=source_key, source_event_id=data['request_id']).first()
    if existing:
        return replay(existing, digest)
    try:
        facility = Facility.objects.get(pk=data['facility_id'])
    except Facility.DoesNotExist:
        raise NotFound('Không tìm thấy cơ sở.')
    received_at = timezone.now()
    occurred_at = data.get('occurred_at', received_at)
    day = occurred_at.astimezone(BUSINESS_TZ).date()
    if (day >= received_at.astimezone(BUSINESS_TZ).date() and employee.status == 'ACTIVE'
            and employee.hired_on <= day and (not employee.ended_on or day <= employee.ended_on)
            and employee.home_facility.is_active
            and not WorkSchedule.objects.filter(employee=employee, work_date=day).exists()):
        from .support_services import create_demo_schedule
        create_demo_schedule(employee.id, day, automatic=True)
    schedule = WorkSchedule.objects.filter(employee=employee, work_date=day, status='SCHEDULED').first()
    previous = AttendanceScan.objects.filter(employee=employee, outcome='ACCEPTED').order_by('-occurred_at', '-id').first()
    events = effective_events(employee.id, day)
    last = events[-1] if events else None
    outcome, code, message, event_type = 'ACCEPTED', 'OK', '', None
    warnings = []
    challenge = None
    qr_error = None
    if channel == 'QR' and data['qr_token']:
        token_hash = hashlib.sha256(data['qr_token'].encode('utf-8')).digest()
        challenge = QrChallenge.objects.select_for_update().filter(nonce_hash=token_hash).first()
        if challenge is None:
            qr_error = ('QR_INVALID', 'Mã QR không hợp lệ.')
        elif challenge.facility_id != facility.id:
            qr_error = ('QR_WRONG_FACILITY', 'Mã QR không thuộc cơ sở đã chọn.')
        elif challenge.revoked_at is not None:
            qr_error = ('QR_REVOKED', 'Mã QR đã bị thu hồi.')
        elif received_at < challenge.issued_at or received_at >= challenge.expires_at:
            qr_error = ('QR_EXPIRED', 'Mã QR đã hết hạn.')
        elif AttendanceScan.objects.filter(employee=employee, qr_challenge=challenge,
                                          source_type='MOBILE_QR', outcome='ACCEPTED').exists():
            qr_error = ('QR_ALREADY_USED', 'Bạn đã sử dụng mã QR này.')
    if not facility.is_active:
        outcome, code, message = 'REJECTED', 'FACILITY_INACTIVE', 'Cơ sở đã ngừng hoạt động.'
    elif employee.status != 'ACTIVE' or day < employee.hired_on or (employee.ended_on and day > employee.ended_on):
        outcome, code, message = 'REJECTED', 'EMPLOYEE_INACTIVE', 'Nhân viên không trong thời gian làm việc hợp lệ.'
    elif channel == 'QR' and qr_error:
        outcome, (code, message) = 'REJECTED', qr_error
    elif channel == 'FACE' and data['recognition'] != 'MATCH':
        code = data['recognition']
        outcome, message = 'REJECTED', ('Không tìm thấy khuôn mặt.' if code == 'NO_FACE' else 'Khuôn mặt chưa đăng ký.')
    elif (previous and occurred_at < previous.occurred_at) or (last and occurred_at < last['time']):
        outcome, code, message = 'REJECTED', 'BACKDATED_SCAN', 'Giờ demo lùi trước lượt đã có; hãy chọn thời gian mới hơn.'
    elif previous and (occurred_at - previous.occurred_at).total_seconds() < facility.min_scan_interval_seconds:
        outcome, code, message = 'IGNORED', 'COOLDOWN', f'Hai lượt phải cách nhau ít nhất {facility.min_scan_interval_seconds} giây.'
    elif channel == 'QR' and (not data['qr_token'] or data['gps_status'] != 'IN_RANGE'):
        outcome = 'PENDING_REVIEW'
        code = 'QR_MISSING' if not data['qr_token'] else 'GPS_' + data['gps_status']
        message = ('Chưa có mã QR. Đã gửi yêu cầu xác minh hiện diện.' if not data['qr_token'] else
                   'Vị trí chưa đủ căn cứ. Đã gửi yêu cầu xác minh hiện diện.')
    else:
        event_type = 'OUT' if last and last['type'] == 'IN' and last['facility_id'] == facility.id else 'IN'
        if last and last['type'] == 'IN' and last['facility_id'] != facility.id:
            warnings.append('MISSING_PREVIOUS_OUT')
        if not schedule:
            warnings.append('NO_SCHEDULE')
        elif schedule.locked_at:
            warnings.append('LOCKED_SCHEDULE_LATE_DATA')
        message = f'Xin chào {employee.full_name}, mời vào.' if event_type == 'IN' else f'Xin tạm biệt {employee.full_name}.'
    alert = None
    if outcome == 'ACCEPTED':
        home_id = schedule.owner_facility_id if schedule else employee.home_facility_id
        # Assignment is checked by employee, work date and destination; arriving
        # earlier or leaving later than its planned window is still supported work.
        assigned = schedule and SupportAssignment.objects.filter(schedule=schedule, to_facility=facility,
                        status__in=['PLANNED', 'CONFIRMED']).exists()
        if facility.id != home_id and not assigned:
            warnings.append('SUPPORT_UNASSIGNED')
            alert, created = AttendanceAlert.objects.get_or_create(employee=employee, facility=facility,
                work_date=day, alert_type='SUPPORT_UNASSIGNED', defaults={
                    'first_seen_at': occurred_at, 'last_seen_at': occurred_at, 'status': 'OPEN'})
            if not created:
                if alert.status == 'VERIFIED':
                    AuditLog.objects.create(actor_type='SYSTEM', action='REOPEN_SUPPORT_ALERT',
                        entity_type='attendance_alerts', entity_id=alert.id,
                        before_data={'status': alert.status, 'verified_by': alert.verified_by_id,
                                     'verified_at': alert.verified_at.isoformat() if alert.verified_at else None,
                                     'review_note': alert.review_note}, after_data={'status': 'OPEN'},
                        reason='Có lượt chấm mới chưa được xác minh.')
                alert.last_seen_at = max(alert.last_seen_at, occurred_at)
                alert.first_seen_at = min(alert.first_seen_at, occurred_at)
                alert.status, alert.verified_by_id, alert.verified_at, alert.review_note = 'OPEN', None, None, None
                alert.save(update_fields=['first_seen_at', 'last_seen_at', 'status', 'verified_by', 'verified_at', 'review_note', 'updated_at'])
    if outcome != 'ACCEPTED':
        message = 'Không ghi nhận. ' + message
    scan = AttendanceScan.objects.create(employee=employee, facility=facility, actor_user=None,
        source_type='DEMO' if channel == 'FACE' else 'MOBILE_QR', source_key=source_key, source_event_id=data['request_id'], payload_hash=digest,
        occurred_at=occurred_at, received_at=received_at, outcome=outcome, event_type=event_type,
        reason_code=code, alert=alert, qr_challenge=challenge, decision_snapshot={
            'channel': channel, 'gps_status': data.get('gps_status'), 'gps_mode': 'SIMULATED' if channel == 'QR' else None,
            'inference_version': 'demo-v1', 'previous_event': last['ref'] if last else None,
            'cooldown_seconds': facility.min_scan_interval_seconds, 'policy_revision': facility.policy_revision,
            'demo_time': 'occurred_at' in data, 'warnings': warnings, 'message': message,
            'employee_name': employee.full_name})
    if outcome == 'PENDING_REVIEW':
        proposed_type = 'OUT' if last and last['type'] == 'IN' and last['facility_id'] == facility.id else 'IN'
        existing_request = AttendanceRequest.objects.filter(
            employee=employee, request_type='PRESENCE', status='PENDING', proposed_facility=facility,
            proposed_occurred_at=occurred_at, proposed_event_type=proposed_type).exists()
        if not existing_request:
            AttendanceRequest.objects.create(employee=employee, schedule=schedule, requested_by=None,
                request_type='PRESENCE', origin_scan=scan, proposed_event_type=proposed_type,
                proposed_facility=facility, proposed_occurred_at=occurred_at, reason=message, status='PENDING')
    return scan, False


@transaction.atomic
def verify_alert(alert_id, review_note, expected_last_seen_at):
    """No login in this demo: actor is SYSTEM; no real reviewer is invented."""
    note = review_note
    item = AttendanceAlert.objects.filter(pk=alert_id).values('employee_id').first()
    if item is None:
        raise NotFound('Không tìm thấy cảnh báo.')
    Employee.objects.select_for_update().get(pk=item['employee_id'])
    alert = AttendanceAlert.objects.select_for_update().get(pk=alert_id)
    if alert.last_seen_at != expected_last_seen_at:
        raise Conflict('Cảnh báo có lượt chấm mới. Hãy tải lại và kiểm tra trước khi xác minh.')
    if alert.status == 'VERIFIED':
        if alert.review_note == note:
            return alert, True
        raise Conflict('Cảnh báo đã được xác minh. Hãy tải lại để xem kết quả.')
    if alert.status != 'OPEN':
        raise Conflict('Trạng thái cảnh báo không còn hợp lệ.')
    alert.status = 'VERIFIED'
    alert.verified_by = None
    alert.verified_at = timezone.now()
    alert.review_note = note
    alert.save(update_fields=['status', 'verified_by', 'verified_at', 'review_note', 'updated_at'])
    AuditLog.objects.create(actor_type='SYSTEM', action='VERIFY_SUPPORT_ALERT',
        entity_type='attendance_alerts', entity_id=alert.id, before_data={'status': 'OPEN'},
        after_data={'status': 'VERIFIED', 'review_note': note, 'mode': 'HR_DEMO'}, reason=note)
    return alert, False


@transaction.atomic
def review_request(request_id, decision, review_note, expected_version):
    """Apply an approved request as an immutable overlay, never rewriting raw scans."""
    note = review_note
    lookup = AttendanceRequest.objects.filter(pk=request_id).values('employee_id', 'schedule_id').first()
    if lookup is None:
        raise NotFound('Không tìm thấy yêu cầu.')
    Employee.objects.select_for_update().get(pk=lookup['employee_id'])
    schedule = None
    if lookup['schedule_id'] is not None:
        schedule = WorkSchedule.objects.select_for_update().filter(pk=lookup['schedule_id']).first()
    item = AttendanceRequest.objects.select_for_update().select_related('target_scan', 'origin_scan').get(pk=request_id)
    if item.schedule_id != lookup['schedule_id']:
        raise Conflict('Lịch ca đã thay đổi. Hãy tải lại yêu cầu.')
    if item.status != 'PENDING':
        if item.status == decision and item.review_note == note and item.version == expected_version + 1:
            return item, True
        raise Conflict('Yêu cầu đã được xử lý. Hãy tải lại.')
    if item.version != expected_version:
        raise Conflict('Yêu cầu đã thay đổi. Hãy tải lại trước khi xử lý.')
    if schedule and schedule.employee_id != item.employee_id:
        raise Conflict('Yêu cầu không thuộc nhân viên trong lịch ca.')
    if decision == 'APPROVED':
        if not schedule and item.request_type != 'PRESENCE':
            raise Conflict('Cần có lịch ca trước khi duyệt yêu cầu này.')
        if schedule and schedule.locked_at:
            raise Conflict('Ngày công đã khóa. Cần mở lại trước khi duyệt.')
        if item.request_type in ('REPLACE_EVENT', 'VOID_EVENT'):
            target = item.target_scan
            if not target or target.employee_id != item.employee_id or target.outcome != 'ACCEPTED':
                raise Conflict('Lượt cần sửa không hợp lệ hoặc không thuộc nhân viên.')
            if schedule and target.occurred_at.astimezone(BUSINESS_TZ).date() != schedule.work_date:
                raise Conflict('Lượt cần sửa không thuộc ngày của lịch ca.')
            if AttendanceRequest.objects.filter(target_scan=target, status='APPROVED').exclude(pk=item.pk).exists():
                raise Conflict('Lượt này đã có điều chỉnh được duyệt.')
        if item.request_type == 'PRESENCE':
            origin = item.origin_scan
            if not origin or origin.employee_id != item.employee_id or origin.outcome != 'PENDING_REVIEW':
                raise Conflict('Bằng chứng hiện diện không hợp lệ hoặc không thuộc nhân viên.')
            if origin.facility_id != item.proposed_facility_id:
                raise Conflict('Cơ sở đề xuất không khớp bằng chứng hiện diện.')
        if item.request_type == 'ADD_EVENT':
            events = effective_events(item.employee_id, schedule.work_date)
            def conflicts(sequence):
                count = int(bool(sequence) and sequence[0]['type'] != 'IN')
                for previous, current in zip(sequence, sequence[1:]):
                    count += int(previous['type'] == current['type'])
                    count += int(previous['type'] == 'IN' and current['type'] == 'OUT' and previous['facility_id'] != current['facility_id'])
                return count
            before_conflicts = conflicts(events)
            events.append({'time': item.proposed_occurred_at, 'type': item.proposed_event_type,
                           'facility_id': item.proposed_facility_id, 'ref': f'request:{item.id}'})
            events.sort(key=lambda event: (event['time'], event['ref']))
            after_conflicts = conflicts(events)
            if after_conflicts > before_conflicts or (before_conflicts and after_conflicts >= before_conflicts):
                raise Conflict('Lượt đề xuất không xử lý được bất thường vào/ra. Hãy kiểm tra lịch sử trước khi duyệt.')
        if schedule and item.proposed_occurred_at and item.proposed_occurred_at.astimezone(BUSINESS_TZ).date() != schedule.work_date:
            raise Conflict('Thời gian đề xuất không thuộc ngày của lịch ca.')
    before = {'status': item.status, 'version': item.version}
    item.status = decision
    item.reviewed_by = None
    item.reviewed_at = timezone.now()
    item.review_note = note
    item.version += 1
    item.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'review_note', 'version', 'updated_at'])
    AuditLog.objects.create(actor_type='SYSTEM', action='REVIEW_ATTENDANCE_REQUEST',
        entity_type='attendance_requests', entity_id=item.id, before_data=before,
        after_data={'status': decision, 'version': item.version, 'review_note': note, 'mode': 'HR_DEMO'}, reason=note)
    return item, False
