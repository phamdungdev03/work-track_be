"""Daily work calculations derived from recorded events and approved corrections."""
from collections import defaultdict
from datetime import datetime, timedelta
from django.db.models import Q
from django.utils import timezone
from .models import AttendanceAlert, AttendanceRequest, AttendanceScan, WorkSchedule
from .services import BUSINESS_TZ, day_bounds


def _minute(value):
    return value.astimezone(BUSINESS_TZ).replace(second=0, microsecond=0)


def summarize(schedule, events, pending, open_alert, now):
    events = sorted(events, key=lambda e: (e['time'], e['ref']))
    reasons = []
    if pending:
        reasons.append('Có yêu cầu chờ xử lý')
    if open_alert:
        reasons.append('Cảnh báo HR chưa xác minh')
    if not schedule and events:
        reasons.append('Chưa có ca làm việc')
    bad = any((e['type'] != ('IN' if i % 2 == 0 else 'OUT')) or
              (i % 2 == 1 and e['facility_id'] != events[i - 1]['facility_id'])
              for i, e in enumerate(events))
    if bad:
        reasons.append('Chuỗi lượt cần xác minh')
    if schedule and not events and now >= schedule.ends_at:
        reasons.append('Có ca nhưng chưa có lượt')
    if schedule and events and events[-1]['type'] == 'IN' and now >= schedule.ends_at:
        reasons.append('Chưa có lượt ra cuối ca')
    supported = bool(schedule and _minute(schedule.starts_at).time().isoformat() == '08:30:00'
                     and _minute(schedule.ends_at).time().isoformat() == '17:30:00'
                     and _minute(schedule.starts_at).date() == _minute(schedule.ends_at).date()
                     and schedule.standard_work_minutes == 480)
    if schedule and not supported:
        reasons.append('Ca này chưa được hỗ trợ tính công')
    complete = bool(supported and events and not bad and len(events) % 2 == 0)
    minutes = late = early = None
    if complete:
        first, last = _minute(events[0]['time']), _minute(events[-1]['time'])
        start, end = _minute(schedule.starts_at), _minute(schedule.ends_at)
        late = max(0, int((first - start).total_seconds() // 60))
        early = max(0, int((end - last).total_seconds() // 60))
        minutes = max(0, min(480, 480 - late - early))
        if first >= end or last <= start:
            minutes = 0
    if schedule and schedule.locked_at:
        # A locked result must never be recalculated from subsequently received scans.
        minutes = late = early = None
        reasons.append('Ngày công đã khóa; cần xem kết quả đã chốt')
    first = next((event for event in events if event['type'] == 'IN'), None)
    last = events[-1] if events and events[-1]['type'] == 'OUT' else None
    return {'employee_id': schedule.employee_id if schedule else None,
            'schedule_end': schedule.ends_at if schedule else None,
            'first_in': first['time'] if first else None, 'last_out': last['time'] if last else None,
            'last_facility_id': events[-1]['facility_id'] if events else None,
            'work_minutes': minutes, 'late_minutes': late, 'early_minutes': early,
            'needs_review': bool(reasons), 'reasons': reasons,
            'status': 'Cần xác minh' if reasons else ('Đã tính công' if minutes is not None else ('Đang trong ca' if events else 'Chưa có lượt'))}


def daily_rows(start_date, end_date, now=None):
    now = now or timezone.now()
    start, _ = day_bounds(start_date)
    _, end = day_bounds(end_date)
    schedules = {(s.employee_id, s.work_date): s for s in WorkSchedule.objects.filter(work_date__range=(start_date, end_date), status='SCHEDULED')}
    scans = AttendanceScan.objects.filter(occurred_at__gte=start, occurred_at__lt=end, employee_id__isnull=False)
    requests = AttendanceRequest.objects.filter(Q(schedule__work_date__range=(start_date, end_date)) | Q(schedule__isnull=True, proposed_occurred_at__gte=start, proposed_occurred_at__lt=end)).select_related('schedule')
    alerts = AttendanceAlert.objects.filter(work_date__range=(start_date, end_date), status='OPEN')
    events, pending, alert_keys = defaultdict(dict), set(), set()
    for scan in scans:
        day = scan.occurred_at.astimezone(BUSINESS_TZ).date()
        key = (scan.employee_id, day)
        if scan.outcome == 'ACCEPTED' and scan.event_type:
            events[key][('scan', scan.id)] = {'time': scan.occurred_at, 'type': scan.event_type, 'facility_id': scan.facility_id, 'ref': f'scan:{scan.id}'}
    for item in requests:
        day = item.schedule.work_date if item.schedule_id else item.proposed_occurred_at.astimezone(BUSINESS_TZ).date()
        key = (item.employee_id, day)
        if item.status == 'PENDING':
            pending.add(key)
        if item.status == 'APPROVED':
            if item.target_scan_id:
                events[key].pop(('scan', item.target_scan_id), None)
            if item.request_type != 'VOID_EVENT' and item.proposed_occurred_at:
                events[key][('request', item.id)] = {'time': item.proposed_occurred_at, 'type': item.proposed_event_type, 'facility_id': item.proposed_facility_id, 'ref': f'request:{item.id}'}
    for alert in alerts:
        alert_keys.add((alert.employee_id, alert.work_date))
    rows = []
    for key in sorted(set(schedules) | set(events) | pending | alert_keys):
        row = summarize(schedules.get(key), list(events[key].values()), key in pending, key in alert_keys, now)
        row['employee_id'], row['date'] = key
        rows.append(row)
    return rows
