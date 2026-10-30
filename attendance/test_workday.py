from datetime import datetime
from zoneinfo import ZoneInfo
from types import SimpleNamespace
from django.test import SimpleTestCase
from .daily_services import summarize

TZ = ZoneInfo('Asia/Ho_Chi_Minh')
def at(hour, minute=0, second=0):
    return datetime(2026, 10, 29, hour, minute, second, tzinfo=TZ)
def event(kind, time, facility=1):
    return {'type': kind, 'time': time, 'facility_id': facility, 'ref': f'{time}-{kind}'}

class DailyWorkTests(SimpleTestCase):
    def setUp(self):
        self.schedule = SimpleNamespace(employee_id=1, starts_at=at(8, 30), ends_at=at(17, 30), standard_work_minutes=480, locked_at=None)
    def run_case(self, events):
        return summarize(self.schedule, events, False, False, at(18))
    def test_late_early_and_outside_hours(self):
        row = self.run_case([event('IN', at(9)), event('OUT', at(17))])
        self.assertEqual((row['late_minutes'], row['early_minutes'], row['work_minutes']), (30, 30, 420))
        self.assertEqual(self.run_case([event('IN', at(8)), event('OUT', at(18))])['work_minutes'], 480)
        self.assertEqual(self.run_case([event('IN', at(18)), event('OUT', at(19))])['work_minutes'], 0)
    def test_seconds_and_intermediate_gaps(self):
        row = self.run_case([event('IN', at(8,30,30)), event('OUT', at(14)), event('IN', at(15)), event('OUT', at(17,29,59))])
        self.assertEqual((row['late_minutes'], row['early_minutes'], row['work_minutes']), (0, 1, 479))
    def test_missing_and_conflicting_events_never_calculate(self):
        for events in ([event('IN', at(9))], [event('IN', at(9)), event('IN', at(10), 2), event('OUT', at(17), 2)]):
            row = self.run_case(events)
            self.assertIsNone(row['work_minutes'])
            self.assertTrue(row['needs_review'])
    def test_support_warning_does_not_remove_work(self):
        row = summarize(self.schedule, [event('IN', at(8,30)), event('OUT', at(17,30))], False, True, at(18))
        self.assertTrue(row['needs_review'])
        self.assertEqual(row['work_minutes'], 480)
    def test_other_shift_is_not_silently_calculated(self):
        self.schedule.starts_at = at(9)
        row = self.run_case([event('IN', at(9)), event('OUT', at(17,30))])
        self.assertIsNone(row['work_minutes'])
        self.assertIn('Ca này chưa được hỗ trợ tính công', row['reasons'])
