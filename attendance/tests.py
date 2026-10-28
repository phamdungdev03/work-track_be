from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
import re
from io import StringIO
from threading import Barrier
from unittest.mock import patch
from django.conf import settings
from django.core.management import call_command
from django.db import connection, close_old_connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from .models import WorkSchedule, Employee, AttendanceScan, AttendanceRequest, AttendanceAlert, AuditLog, QrChallenge
from .serializers import DemoScanSerializer, QrScanSerializer
from .services import effective_events, record_demo_scan, issue_qr, review_request
from .exceptions import Conflict


def seed_database():
    text = (Path(settings.BASE_DIR).parent / 'database' / 'attendance-seed.sql').read_text()
    # Execute seed INSERTs directly inside the already isolated test schema.
    with connection.cursor() as cursor:
        for statement in re.findall(r'INSERT INTO .*?;(?=\n)', text, re.S):
            cursor.execute(statement)


class ApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_database()

    def setUp(self):
        self.client = APIClient()

    def scan(self, request_id='first', employee=1, facility=1, timestamp='2026-10-29T08:30:00+07:00', **extra):
        return self.client.post('/api/scans/demo/', {'request_id': request_id, 'employee_id': employee,
            'facility_id': facility, 'occurred_at': timestamp, **extra}, format='json')

    def test_no_login_or_password_setup_needed(self):
        self.assertEqual(self.client.get('/api/employees/').data['count'], 100)
        self.assertEqual(self.client.get('/api/employees/21/').status_code, 200)
        self.assertEqual(self.client.get('/api/alerts/').status_code, 200)
        self.assertEqual(self.client.post('/api/auth/login/', {}, format='json').status_code, 404)
        response = self.scan()
        self.assertEqual(response.status_code, 201)
        scan = AttendanceScan.objects.get(pk=response.data['scan']['id'])
        self.assertIsNone(scan.actor_user_id)
        self.assertEqual(scan.source_key, 'demo:kiosk')

    def test_database_check(self):
        output = StringIO()
        call_command('check_db', stdout=output)
        self.assertIn('10 bảng', output.getvalue())

    def test_malformed_scan_body_returns_400(self):
        for data in [123, [{}], 'invalid']:
            with self.subTest(data=data):
                self.assertEqual(self.client.post('/api/scans/demo/', data, format='json').status_code, 400)

    def test_unidentified_attempt_visible_without_login(self):
        sample = AttendanceScan.objects.first()
        AttendanceScan.objects.create(employee=None, facility_id=1, source_type='FACE_DEVICE',
            source_key='device:unknown', source_event_id='unknown-face', payload_hash=bytes(32),
            occurred_at=sample.occurred_at, received_at=sample.received_at,
            outcome='REJECTED', event_type=None, reason_code='UNREGISTERED', decision_snapshot={})
        data = self.client.get('/api/scans/?outcome=REJECTED').data
        self.assertTrue(any(row['employee_id'] is None for row in data['results']))


    def test_all_read_endpoints_match_imported_seed(self):
        expected = {'employees':100,'facilities':5,'schedules':300,'support-assignments':26,
                    'scans':635,'alerts':10,'requests':30}
        for endpoint,count in expected.items():
            with self.subTest(endpoint=endpoint):
                result=self.client.get(f'/api/{endpoint}/')
                self.assertEqual(result.status_code,200,result.data)
                self.assertEqual(result.data['count'],count)
        self.assertEqual(self.client.get('/api/health/database/').status_code,200)
        self.assertNotIn('password_hash',str(self.client.get('/api/employees/').data))

    def test_filters_and_date_boundary(self):
        self.assertEqual(self.client.get('/api/employees/?facility_id=1').data['count'],20)
        self.assertEqual(self.client.get('/api/scans/?date=2026-10-26&employee_id=1').data['count'],2)
        self.assertEqual(self.client.get('/api/scans/?date=invalid').status_code,400)
        self.assertEqual(self.client.get('/api/scans/?employee_id=bad').status_code,400)


    def test_in_cooldown_out_and_replay(self):
        first=self.scan()
        self.assertEqual(first.status_code,201,first.data)
        self.assertEqual(first.data['scan']['event_type'],'IN')
        duplicate=self.scan()
        self.assertEqual(duplicate.status_code,200)
        self.assertTrue(duplicate.data['replayed'])
        blocked=self.scan('fast',timestamp='2026-10-29T08:30:03+07:00')
        self.assertEqual(blocked.data['scan']['outcome'],'IGNORED')
        self.assertIsNone(blocked.data['scan']['event_type'])
        out=self.scan('later',timestamp='2026-10-29T08:30:10+07:00')
        self.assertEqual(out.data['scan']['event_type'],'OUT')
        self.assertIn('Xin tạm biệt',out.data['message'])
        self.assertTrue(self.scan('fast',timestamp='2026-10-29T08:30:03+07:00').data['replayed'])

    def test_same_key_different_payload_conflicts(self):
        self.scan()
        self.assertEqual(self.scan(facility=2).status_code,409)

    def test_employee_cooldown_is_independent(self):
        self.scan()
        self.assertEqual(self.scan('other',employee=2).data['scan']['outcome'],'ACCEPTED')

    def test_recognition_failure_does_not_toggle(self):
        self.scan('fail',recognition='NO_FACE')
        self.assertEqual(self.scan('success').data['scan']['event_type'],'IN')

    def test_support_unassigned_groups_alert_without_blocking(self):
        first=self.scan(facility=2)
        out=self.scan('out',facility=2,timestamp='2026-10-29T17:30:00+07:00')
        self.assertEqual(first.data['scan']['outcome'],'ACCEPTED')
        self.assertIn('SUPPORT_UNASSIGNED',first.data['warnings'])
        self.assertEqual(first.data['scan']['alert_id'],out.data['scan']['alert_id'])

    def test_different_facility_in_flags_missing_previous_out(self):
        self.scan()
        response=self.scan('at-b',facility=2,timestamp='2026-10-29T10:30:00+07:00')
        self.assertEqual(response.data['scan']['event_type'],'IN')
        self.assertIn('MISSING_PREVIOUS_OUT',response.data['warnings'])

    def test_backdated_and_inactive(self):
        self.scan()
        self.assertEqual(self.scan('back',timestamp='2026-10-29T08:20:00+07:00').data['scan']['reason_code'],'BACKDATED_SCAN')
        Employee.objects.filter(pk=2).update(status='INACTIVE')
        self.assertEqual(self.scan('inactive',employee=2).data['scan']['reason_code'],'EMPLOYEE_INACTIVE')

    def test_effective_events_include_approved_seed_requests(self):
        day=datetime(2026,10,28).date()
        self.assertEqual([e['type'] for e in effective_events(10,day)],['IN','OUT'])
        self.assertEqual([e['type'] for e in effective_events(5,day)],['IN'])
        self.assertEqual([e['type'] for e in effective_events(19,day)],['IN','OUT'])

    def test_demo_gate_and_explicit_timestamp_zone(self):
        with override_settings(DEMO_MODE=False):
            self.assertEqual(self.scan().status_code,403)
        self.assertEqual(self.scan(timestamp='2026-10-29T08:30:00').status_code,400)
        self.assertEqual(self.scan(event_type='OUT').status_code,400)

    def test_locked_snapshot_is_preserved(self):
        before=WorkSchedule.objects.get(pk=1).locked_result
        response=self.scan('locked',timestamp='2026-10-26T18:00:00+07:00')
        self.assertEqual(response.data['scan']['outcome'],'REJECTED')
        self.assertEqual(WorkSchedule.objects.get(pk=1).locked_result,before)

    def test_liveness_does_not_need_database(self):
        with patch('django.db.backends.utils.CursorWrapper.execute',side_effect=AssertionError('Unexpected DB access')):
            self.assertEqual(APIClient().get('/api/health/').status_code,200)


class QrApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_database()

    def setUp(self):
        self.client = APIClient()

    def issue(self, facility=2, previous=None):
        data = {'facility_id': facility}
        if previous:
            data['previous_token'] = previous
        response = self.client.post('/api/qr/challenges/', data, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        return response.data['token']

    def scan_qr(self, token, key='qr-1', employee=1, facility=2, gps='IN_RANGE', time='2026-10-29T08:30:00+07:00'):
        return self.client.post('/api/qr/scans/', {'request_id': key, 'employee_id': employee,
            'facility_id': facility, 'qr_token': token, 'gps_status': gps, 'occurred_at': time}, format='json')

    def test_qr_in_out_shared_with_face_and_unassigned_warning(self):
        face = self.client.post('/api/scans/demo/', {'request_id':'face-1', 'employee_id':1,
            'facility_id':1, 'occurred_at':'2026-10-29T08:00:00+07:00'}, format='json')
        self.assertEqual(face.data['scan']['event_type'], 'IN')
        token = self.issue()
        qr = self.scan_qr(token)
        self.assertEqual(qr.data['scan']['event_type'], 'IN')
        self.assertEqual(qr.data['scan']['source_type'], 'MOBILE_QR')
        self.assertIn('MISSING_PREVIOUS_OUT', qr.data['warnings'])
        self.assertIn('SUPPORT_UNASSIGNED', qr.data['warnings'])
        self.assertIsNone(AttendanceScan.objects.get(pk=qr.data['scan']['id']).actor_user_id)
        second = self.issue()
        out = self.scan_qr(second, 'qr-out', time='2026-10-29T08:31:00+07:00')
        self.assertEqual(out.data['scan']['event_type'], 'OUT')

    def test_same_qr_two_people_and_per_employee_reuse(self):
        token = self.issue()
        first = self.scan_qr(token)
        second = self.scan_qr(token, key='qr-2', employee=2)
        duplicate = self.scan_qr(token, key='qr-3', time='2026-10-29T08:31:00+07:00')
        self.assertEqual(first.data['scan']['outcome'], 'ACCEPTED')
        self.assertEqual(second.data['scan']['outcome'], 'ACCEPTED')
        self.assertEqual(duplicate.data['scan']['reason_code'], 'QR_ALREADY_USED')
        self.assertIsNone(duplicate.data['scan']['event_type'])

    def test_idempotent_retry_after_expiry(self):
        token = self.issue()
        first = self.scan_qr(token)
        challenge = QrChallenge.objects.get(pk=AttendanceScan.objects.get(pk=first.data['scan']['id']).qr_challenge_id)
        with patch('attendance.services.timezone.now', return_value=challenge.expires_at + timedelta(seconds=1)):
            retry = self.scan_qr(token)
            new = self.scan_qr(token, key='qr-new')
        self.assertEqual(retry.status_code, 200)
        self.assertTrue(retry.data['replayed'])
        self.assertEqual(new.data['scan']['reason_code'], 'QR_EXPIRED')
        self.assertEqual(self.scan_qr(token, gps='OUT_OF_RANGE').status_code, 409)

    def test_wrong_facility_tampered_and_revoked_are_rejected(self):
        token = self.issue()
        self.assertEqual(self.scan_qr(token, facility=3).data['scan']['reason_code'], 'QR_WRONG_FACILITY')
        self.assertEqual(self.scan_qr(token + 'x', key='tamper').data['scan']['reason_code'], 'QR_INVALID')
        self.issue(previous=token)
        self.assertEqual(self.scan_qr(token, key='revoked').data['scan']['reason_code'], 'QR_REVOKED')

    def test_missing_gps_or_qr_pending_without_consuming(self):
        token = self.issue()
        pending = self.scan_qr(token, gps='UNAVAILABLE')
        self.assertEqual(pending.data['scan']['outcome'], 'PENDING_REVIEW')
        self.assertIsNone(pending.data['scan']['event_type'])
        req = AttendanceRequest.objects.get(origin_scan_id=pending.data['scan']['id'])
        self.assertEqual(req.status, 'PENDING')
        self.assertIsNone(req.requested_by_id)
        results = self.client.get('/api/requests/?employee_id=1&date=2026-10-29&status=PENDING')
        self.assertEqual(results.data['count'], 1)
        duplicate = self.scan_qr(token, key='same-time', gps='UNAVAILABLE')
        self.assertEqual(duplicate.data['scan']['outcome'], 'PENDING_REVIEW')
        self.assertEqual(AttendanceRequest.objects.filter(employee_id=1, request_type='PRESENCE', proposed_occurred_at=req.proposed_occurred_at).count(), 1)
        accepted = self.scan_qr(token, key='valid')
        self.assertEqual(accepted.data['scan']['event_type'], 'IN')
        missing = self.scan_qr('', key='missing', employee=2)
        self.assertEqual(missing.data['scan']['reason_code'], 'QR_MISSING')
        outside = self.scan_qr(token, key='outside', employee=3, gps='OUT_OF_RANGE')
        self.assertEqual(outside.data['scan']['reason_code'], 'GPS_OUT_OF_RANGE')

    def test_qr_invalid_does_not_override_face_direction_or_cooldown(self):
        token = self.issue()
        invalid = self.scan_qr(token + 'x')
        self.assertEqual(invalid.data['scan']['outcome'], 'REJECTED')
        face = self.client.post('/api/scans/demo/', {'request_id':'face-1', 'employee_id':1,
            'facility_id':2, 'occurred_at':'2026-10-29T08:30:00+07:00'}, format='json')
        self.assertEqual(face.data['scan']['event_type'], 'IN')
        early = self.scan_qr(token, 'early', time='2026-10-29T08:30:03+07:00')
        self.assertEqual(early.data['scan']['reason_code'], 'COOLDOWN')
        allowed = self.scan_qr(token, 'allowed', time='2026-10-29T08:30:11+07:00')
        self.assertEqual(allowed.data['scan']['event_type'], 'OUT')

    def test_demo_gate(self):
        with override_settings(DEMO_MODE=False):
            self.assertEqual(self.client.post('/api/qr/challenges/', {'facility_id':2}, format='json').status_code,403)
            self.assertEqual(self.scan_qr('', gps='UNAVAILABLE').status_code,403)


class HrReviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_database()

    def setUp(self):
        self.client = APIClient()

    def test_verify_alert_requires_note_is_replay_safe_and_preserves_scans(self):
        alert = AttendanceAlert.objects.filter(status='OPEN').first()
        count = AttendanceScan.objects.filter(employee=alert.employee).count()
        url = f'/api/alerts/{alert.id}/verify/'
        payload = {'review_note': 'Đã xác minh điều động', 'expected_last_seen_at': alert.last_seen_at.isoformat()}
        self.assertEqual(self.client.post(url, {**payload, 'review_note': ' '}, format='json').status_code, 400)
        first = self.client.post(url, payload, format='json')
        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(first.data['alert']['status'], 'VERIFIED')
        self.assertIsNone(first.data['alert']['verified_by'])
        self.assertTrue(self.client.post(url, payload, format='json').data['replayed'])
        self.assertEqual(self.client.post(url, {**payload, 'review_note':'Khác'}, format='json').status_code,409)
        self.assertEqual(AttendanceScan.objects.filter(employee=alert.employee).count(), count)
        self.assertEqual(AuditLog.objects.filter(entity_type='attendance_alerts', entity_id=alert.id, action='VERIFY_SUPPORT_ALERT').count(),1)

    def test_stale_alert_is_not_verified(self):
        alert = AttendanceAlert.objects.filter(status='OPEN').first()
        old = alert.last_seen_at
        AttendanceAlert.objects.filter(pk=alert.id).update(last_seen_at=old + timedelta(seconds=1))
        response = self.client.post(f'/api/alerts/{alert.id}/verify/', {'review_note':'Đã kiểm tra', 'expected_last_seen_at': old.isoformat()},format='json')
        self.assertEqual(response.status_code,409)
        alert.refresh_from_db()
        self.assertEqual(alert.status,'OPEN')

    def test_approve_existing_request_uses_overlay_and_retry(self):
        item = AttendanceRequest.objects.filter(request_type='ADD_EVENT',status='PENDING').first()
        raw = list(AttendanceScan.objects.filter(employee=item.employee).values_list('id','outcome','event_type'))
        url = f'/api/requests/{item.id}/review/'
        payload = {'decision':'APPROVED', 'review_note':'Đã đối chiếu giờ ra', 'expected_version':item.version}
        response = self.client.post(url,payload,format='json')
        self.assertEqual(response.status_code,200,response.data)
        self.assertTrue(self.client.post(url,payload,format='json').data['replayed'])
        self.assertEqual(self.client.post(url,{**payload,'decision':'REJECTED'},format='json').status_code,409)
        self.assertEqual(list(AttendanceScan.objects.filter(employee=item.employee).values_list('id','outcome','event_type')),raw)
        self.assertTrue(any(e['ref'] == f'request:{item.id}' for e in effective_events(item.employee_id, item.schedule.work_date)))
        self.assertEqual(AuditLog.objects.filter(entity_type='attendance_requests',entity_id=item.id,action='REVIEW_ATTENDANCE_REQUEST').count(),1)

    def test_reject_never_adds_effective_event(self):
        item = AttendanceRequest.objects.filter(request_type='ADD_EVENT',status='PENDING').first()
        response = self.client.post(f'/api/requests/{item.id}/review/', {'decision':'REJECTED','review_note':'Thiếu căn cứ','expected_version':item.version},format='json')
        self.assertEqual(response.status_code,200)
        self.assertFalse(any(e['ref'] == f'request:{item.id}' for e in effective_events(item.employee_id,item.schedule.work_date)))

    def test_presence_without_schedule_can_be_approved_and_next_scan_out(self):
        pending=self.client.post('/api/qr/scans/', {'request_id':'presence-hr','employee_id':1,'facility_id':1,'gps_status':'UNAVAILABLE','qr_token':'','occurred_at':'2026-10-29T08:30:00+07:00'},format='json')
        item=AttendanceRequest.objects.get(origin_scan_id=pending.data['scan']['id'])
        self.assertIsNone(item.schedule_id)
        approved=self.client.post(f'/api/requests/{item.id}/review/', {'decision':'APPROVED','review_note':'Đã xác minh nhân viên có mặt','expected_version':item.version},format='json')
        self.assertEqual(approved.status_code,200,approved.data)
        scan=self.client.post('/api/scans/demo/', {'request_id':'after-presence','employee_id':1,'facility_id':1,'occurred_at':'2026-10-29T17:30:00+07:00'},format='json')
        self.assertEqual(scan.data['scan']['event_type'],'OUT')
        origin=AttendanceScan.objects.get(pk=item.origin_scan_id)
        self.assertEqual(origin.outcome,'PENDING_REVIEW')
        self.assertIsNone(origin.event_type)

    def test_locked_schedule_prevents_approval_but_allows_reject(self):
        item=AttendanceRequest.objects.filter(request_type='ADD_EVENT',status='PENDING').first()
        schedule=item.schedule
        WorkSchedule.objects.filter(pk=schedule.id).update(locked_at=timezone.now(),locked_by_id=101,locked_result={'regular_minutes': 480})
        payload={'decision':'APPROVED','review_note':'Đủ căn cứ','expected_version':item.version}
        self.assertEqual(self.client.post(f'/api/requests/{item.id}/review/',payload,format='json').status_code,409)
        self.assertEqual(self.client.post(f'/api/requests/{item.id}/review/',{**payload,'decision':'REJECTED'},format='json').status_code,200)
        self.assertEqual(WorkSchedule.objects.get(pk=schedule.id).locked_result,{'regular_minutes':480})

    def test_disabled_demo_blocks_mutations(self):
        alert=AttendanceAlert.objects.filter(status='OPEN').first()
        with override_settings(DEMO_MODE=False):
            self.assertEqual(self.client.post(f'/api/alerts/{alert.id}/verify/',{'review_note':'x','expected_last_seen_at':alert.last_seen_at.isoformat()},format='json').status_code,403)
            item=AttendanceRequest.objects.filter(status='PENDING').first()
            self.assertEqual(self.client.post(f'/api/requests/{item.id}/review/',{'decision':'APPROVED','review_note':'x','expected_version':item.version},format='json').status_code,403)


class SupportAssignmentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_database()

    def setUp(self):
        self.client = APIClient()
        self.payload = {'request_id': 'support-test-1', 'schedule_id': 201,
            'from_facility_id': 1, 'to_facility_id': 2,
            'depart_at': '2026-10-28T09:00:00+07:00',
            'expected_arrival_at': '2026-10-28T09:15:00+07:00',
            'support_ends_at': '2026-10-28T10:00:00+07:00', 'reason': 'Hỗ trợ cơ sở B'}

    def create(self, **changes):
        return self.client.post('/api/support-assignments/create/', {**self.payload, **changes}, format='json')

    def test_create_retry_edit_cancel_and_audit(self):
        response = self.create()
        self.assertEqual(response.status_code, 201, response.data)
        item = response.data['assignment']
        self.assertEqual(item['status'], 'CONFIRMED')
        self.assertIsNone(item['created_by'])
        self.assertNotIn('creation_hash', item)
        self.assertTrue(self.create().data['replayed'])
        self.assertEqual(self.create(reason='Nội dung khác').status_code,409)
        self.assertEqual(AuditLog.objects.filter(entity_type='support_assignments',entity_id=item['id'],action='CREATE_SUPPORT_ASSIGNMENT').count(),1)
        newdata = {key: value for key,value in self.payload.items() if key not in ('request_id','schedule_id')}
        newdata.update({'expected_updated_at': item['updated_at'], 'reason': 'Đã đổi nội dung'})
        edited = self.client.put(f"/api/support-assignments/{item['id']}/", newdata, format='json')
        self.assertEqual(edited.status_code,200,edited.data)
        self.assertEqual(self.client.put(f"/api/support-assignments/{item['id']}/", newdata, format='json').status_code,409)
        cancel = self.client.post(f"/api/support-assignments/{item['id']}/cancel/", {'expected_updated_at': edited.data['assignment']['updated_at'],'reason':'Không còn nhu cầu'}, format='json')
        self.assertEqual(cancel.status_code,200,cancel.data)
        self.assertEqual(cancel.data['assignment']['status'],'CANCELLED')
        self.assertEqual(AuditLog.objects.filter(entity_type='support_assignments',entity_id=item['id']).count(),3)
        self.assertEqual(self.client.put(f"/api/support-assignments/{item['id']}/", {**newdata,'expected_updated_at':cancel.data['assignment']['updated_at']}, format='json').status_code,409)

    def test_validation_for_ca_site_time_and_overlap(self):
        self.assertEqual(self.create(schedule_id=99999).status_code,404)
        self.assertEqual(self.create(to_facility_id=1).status_code,400)
        self.assertEqual(self.create(to_facility_id=9999).status_code,400)
        self.assertEqual(self.create(depart_at='2026-10-28T08:00:00+07:00').status_code,400)
        self.assertEqual(self.create(expected_arrival_at='2026-10-28T10:30:00+07:00').status_code,400)
        first=self.create();self.assertEqual(first.status_code,201)
        self.assertEqual(self.create(request_id='support-overlap').status_code,409)
        adjacent=self.create(request_id='support-next',depart_at='2026-10-28T10:00:00+07:00',expected_arrival_at='2026-10-28T10:15:00+07:00',support_ends_at='2026-10-28T11:00:00+07:00')
        self.assertEqual(adjacent.status_code,201,adjacent.data)

    def test_locked_cancelled_and_inactive_cases(self):
        WorkSchedule.objects.filter(pk=201).update(locked_at=timezone.now(),locked_by_id=101,locked_result={'regular_minutes':480})
        self.assertEqual(self.create().status_code,409)
        WorkSchedule.objects.filter(pk=201).update(locked_at=None,locked_by_id=None,locked_result=None,status='CANCELLED')
        self.assertEqual(self.create().status_code,409)
        WorkSchedule.objects.filter(pk=201).update(status='SCHEDULED')
        Employee.objects.filter(pk=1).update(status='INACTIVE')
        self.assertEqual(self.create().status_code,400)

    def test_late_assignment_keeps_alert_open_and_original_scans(self):
        alert = AttendanceAlert.objects.get(employee_id=7, facility_id=2, work_date='2026-10-28')
        before = list(AttendanceScan.objects.filter(employee_id=7).values_list('id','outcome','event_type'))
        result=self.create(request_id='late-support', schedule_id=207, depart_at='2026-10-28T10:00:00+07:00', expected_arrival_at='2026-10-28T10:30:00+07:00', support_ends_at='2026-10-28T17:30:00+07:00')
        self.assertEqual(result.status_code,201,result.data)
        alert.refresh_from_db()
        self.assertEqual(alert.status,'OPEN')
        self.assertEqual(list(AttendanceScan.objects.filter(employee_id=7).values_list('id','outcome','event_type')),before)

    def test_create_demo_shift_is_explicit_and_idempotent(self):
        payload = {'employee_id': 1, 'work_date': '2026-10-29'}
        response = self.client.post('/api/schedules/demo-create/', payload, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        shift = response.data['schedule']
        self.assertIsNone(shift['created_by'])
        self.assertEqual(shift['standard_work_minutes'], 480)
        self.assertFalse(shift['policy_snapshot']['break_confirmed'])
        retry = self.client.post('/api/schedules/demo-create/', payload, format='json')
        self.assertEqual(retry.status_code, 200)
        self.assertTrue(retry.data['replayed'])
        self.assertEqual(AuditLog.objects.filter(entity_type='work_schedules', entity_id=shift['id'], action='CREATE_DEMO_SCHEDULE').count(),1)
        support = self.create(request_id='shift-support', schedule_id=shift['id'],
            depart_at='2026-10-29T10:00:00+07:00', expected_arrival_at='2026-10-29T10:30:00+07:00',
            support_ends_at='2026-10-29T17:30:00+07:00')
        self.assertEqual(support.status_code,201,support.data)
        scan = self.client.post('/api/scans/demo/', {'request_id':'assigned-next','employee_id':1,'facility_id':2,
            'occurred_at':'2026-10-29T10:30:00+07:00'}, format='json')
        self.assertEqual(scan.data['scan']['outcome'],'ACCEPTED')
        self.assertNotIn('SUPPORT_UNASSIGNED',scan.data['warnings'])

    def test_demo_shift_inactive_or_cancelled_not_silently_reactivated(self):
        Employee.objects.filter(pk=2).update(status='INACTIVE')
        self.assertEqual(self.client.post('/api/schedules/demo-create/', {'employee_id':2,'work_date':'2026-10-29'},format='json').status_code,400)
        WorkSchedule.objects.filter(pk=201).update(status='CANCELLED')
        self.assertEqual(self.client.post('/api/schedules/demo-create/', {'employee_id':1,'work_date':'2026-10-28'},format='json').status_code,409)
        with override_settings(DEMO_MODE=False):
            self.assertEqual(self.client.post('/api/schedules/demo-create/', {'employee_id':1,'work_date':'2026-10-29'},format='json').status_code,403)

    def test_new_assignment_stops_new_warning_without_closing_old_alert(self):
        shift = self.client.post('/api/schedules/demo-create/', {'employee_id':1, 'work_date':'2026-10-29'}, format='json').data['schedule']
        first = self.client.post('/api/scans/demo/', {'request_id':'before-assignment', 'employee_id':1, 'facility_id':2,
            'occurred_at':'2026-10-29T10:30:00+07:00'}, format='json')
        self.assertIn('SUPPORT_UNASSIGNED',first.data['warnings'])
        alert_id = first.data['scan']['alert_id']
        assignment = self.create(request_id='after-scan', schedule_id=shift['id'],
            depart_at='2026-10-29T10:00:00+07:00', expected_arrival_at='2026-10-29T10:30:00+07:00',
            support_ends_at='2026-10-29T17:30:00+07:00')
        self.assertEqual(assignment.status_code,201,assignment.data)
        later = self.client.post('/api/scans/demo/', {'request_id':'after-assignment', 'employee_id':1, 'facility_id':2,
            'occurred_at':'2026-10-29T17:30:00+07:00'}, format='json')
        self.assertEqual(later.data['scan']['event_type'], 'OUT')
        self.assertNotIn('SUPPORT_UNASSIGNED',later.data['warnings'])
        self.assertEqual(AttendanceAlert.objects.get(pk=alert_id).status, 'OPEN')

    def test_invalid_body_and_demo_gate(self):
        self.assertEqual(self.create(reason='   ').status_code,400)
        self.assertEqual(self.create(status='CONFIRMED').status_code,400)
        with override_settings(DEMO_MODE=False):
            self.assertEqual(self.create().status_code,403)


class ConcurrentScanTests(TransactionTestCase):
    def setUp(self):
        seed_database()

    def tearDown(self):
        tables=['audit_logs','attendance_requests','attendance_scans','attendance_alerts','qr_challenges',
                'support_assignments','work_schedules','users','employees','facilities']
        with connection.cursor() as cursor:
            for table in tables:
                cursor.execute(f'DELETE FROM {table}')

    def test_simultaneous_approvals_of_same_scan_only_one_wins(self):
        target = AttendanceScan.objects.filter(employee_id=1, outcome='ACCEPTED').order_by('-id').first()
        schedule = WorkSchedule.objects.get(employee_id=1, work_date='2026-10-28')
        items = [AttendanceRequest.objects.create(employee_id=1, schedule=schedule, requested_by_id=1,
            request_type='REPLACE_EVENT', target_scan=target, proposed_event_type='IN',
            proposed_facility_id=1, proposed_occurred_at=target.occurred_at,
            reason='Thử phê duyệt đồng thời', status='PENDING') for _ in range(2)]
        barrier = Barrier(2)
        def submit(item):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    review_request(item.id, 'APPROVED', 'Đã xác minh', item.version)
                    return 'APPROVED'
                except Conflict:
                    return 'CONFLICT'
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(submit, items))
        self.assertCountEqual(outcomes, ['APPROVED', 'CONFLICT'])
        self.assertEqual(AttendanceRequest.objects.filter(target_scan=target, status='APPROVED').count(), 1)

    def test_concurrent_overlapping_support_only_one_created(self):
        barrier = Barrier(2)
        def submit(index):
            close_old_connections()
            try:
                client = APIClient()
                barrier.wait(timeout=10)
                response = client.post('/api/support-assignments/create/', {
                    'request_id':f'support-race-{index}','schedule_id':201,'from_facility_id':1,'to_facility_id':2,
                    'depart_at':'2026-10-28T09:00:00+07:00','expected_arrival_at':'2026-10-28T09:15:00+07:00',
                    'support_ends_at':'2026-10-28T10:00:00+07:00','reason':'Điều động'},format='json')
                return response.status_code
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes=list(executor.map(submit,[1,2]))
        self.assertCountEqual(outcomes,[201,409])

    def test_same_qr_concurrent_scan_only_one_per_employee(self):
        token = issue_qr(2)['token']
        barrier = Barrier(2)
        def submit(index):
            close_old_connections()
            try:
                serializer = QrScanSerializer(data={'request_id': f'qr-parallel-{index}', 'employee_id': 1,
                    'facility_id': 2, 'occurred_at': '2026-10-29T08:30:00+07:00',
                    'gps_status': 'IN_RANGE', 'qr_token': token})
                serializer.is_valid(raise_exception=True)
                barrier.wait(timeout=10)
                scan, _ = record_demo_scan(serializer.validated_data, channel='QR')
                return scan.outcome
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(submit, [1, 2]))
        self.assertCountEqual(outcomes, ['ACCEPTED', 'REJECTED'])
        self.assertEqual(AttendanceScan.objects.filter(source_key='demo:mobile-qr', outcome='ACCEPTED').count(), 1)

    def test_simultaneous_first_scans_only_accept_once(self):
        barrier=Barrier(2)
        def submit(index):
            close_old_connections()
            try:
                serializer=DemoScanSerializer(data={'request_id':f'parallel-{index}','employee_id':1,
                    'facility_id':1,'occurred_at':'2026-10-29T08:30:00+07:00'})
                serializer.is_valid(raise_exception=True)
                barrier.wait(timeout=10)
                scan,_=record_demo_scan(serializer.validated_data)
                return scan.outcome
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes=list(executor.map(submit,[1,2]))
        self.assertCountEqual(outcomes,['ACCEPTED','IGNORED'])
