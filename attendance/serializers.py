import re
from collections.abc import Mapping
from rest_framework import serializers
from .models import (Employee, Facility, WorkSchedule, SupportAssignment,
                     AttendanceScan, AttendanceAlert, AttendanceRequest)


class EmployeeSerializer(serializers.ModelSerializer):
    home_facility_name = serializers.CharField(source='home_facility.name', read_only=True)

    class Meta:
        model = Employee
        fields = ['id', 'employee_code', 'full_name', 'home_facility_id',
                  'home_facility_name', 'hired_on', 'ended_on', 'status']


class FacilitySerializer(serializers.ModelSerializer):
    class Meta:
        model = Facility
        fields = ['id', 'code', 'name', 'address', 'is_active', 'latitude', 'longitude',
                  'geofence_radius_m', 'min_scan_interval_seconds', 'qr_ttl_seconds']


class ScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkSchedule
        fields = '__all__'


class SupportSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupportAssignment
        exclude = ['creation_hash']


class ScanSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source='employee.full_name', read_only=True, default=None)
    facility_name = serializers.CharField(source='facility.name', read_only=True)

    class Meta:
        model = AttendanceScan
        fields = ['id', 'employee_id', 'employee_name', 'facility_id', 'facility_name',
                  'source_type', 'occurred_at', 'received_at', 'outcome', 'event_type',
                  'reason_code', 'decision_snapshot', 'alert_id']


class AlertSerializer(serializers.ModelSerializer):
    class Meta:
        model = AttendanceAlert
        fields = '__all__'


class RequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = AttendanceRequest
        fields = '__all__'


class QuerySerializer(serializers.Serializer):
    employee_id = serializers.IntegerField(min_value=1, required=False)
    alert_id = serializers.IntegerField(min_value=1, required=False)
    facility_id = serializers.IntegerField(min_value=1, required=False)
    date = serializers.DateField(required=False)
    search = serializers.CharField(max_length=100, required=False)
    status = serializers.CharField(max_length=30, required=False)
    outcome = serializers.ChoiceField(choices=['ACCEPTED', 'IGNORED', 'REJECTED', 'PENDING_REVIEW'], required=False)


class OffsetDateTimeField(serializers.DateTimeField):
    def to_internal_value(self, value):
        if not isinstance(value, str) or not re.search(r'(Z|[+-]\d{2}:\d{2})$', value):
            raise serializers.ValidationError('Giờ demo cần múi giờ, ví dụ 2026-10-29T08:30:00+07:00.')
        return super().to_internal_value(value)


class DemoScanSerializer(serializers.Serializer):
    request_id = serializers.RegexField(r'^[A-Za-z0-9_.:-]+$', max_length=100)
    employee_id = serializers.IntegerField(min_value=1)
    facility_id = serializers.IntegerField(min_value=1)
    occurred_at = OffsetDateTimeField(required=False)
    recognition = serializers.ChoiceField(choices=['MATCH', 'NO_FACE', 'UNREGISTERED'], default='MATCH')

    def to_internal_value(self, data):
        if not isinstance(data, Mapping):
            return super().to_internal_value(data)
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError({key: 'Trường không được hỗ trợ.' for key in sorted(unknown)})
        return super().to_internal_value(data)


class QrIssueSerializer(serializers.Serializer):
    facility_id = serializers.IntegerField(min_value=1)
    previous_token = serializers.CharField(max_length=128, required=False, allow_blank=False)


class QrScanSerializer(serializers.Serializer):
    request_id = serializers.RegexField(r'^[A-Za-z0-9_.:-]+$', max_length=100)
    employee_id = serializers.IntegerField(min_value=1)
    facility_id = serializers.IntegerField(min_value=1)
    occurred_at = OffsetDateTimeField(required=False)
    qr_token = serializers.CharField(max_length=128, required=False, allow_blank=True, default='')
    gps_status = serializers.ChoiceField(choices=['IN_RANGE', 'OUT_OF_RANGE', 'UNAVAILABLE'])

    def to_internal_value(self, data):
        if not isinstance(data, Mapping):
            return super().to_internal_value(data)
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError({key: 'Trường không được hỗ trợ.' for key in sorted(unknown)})
        return super().to_internal_value(data)


class VerifyAlertSerializer(serializers.Serializer):
    review_note = serializers.CharField(max_length=1000, trim_whitespace=True)
    expected_last_seen_at = OffsetDateTimeField()


class ReviewRequestSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=['APPROVED', 'REJECTED'])
    review_note = serializers.CharField(max_length=1000, trim_whitespace=True)
    expected_version = serializers.IntegerField(min_value=1)


class SupportFieldsSerializer(serializers.Serializer):
    from_facility_id = serializers.IntegerField(min_value=1)
    to_facility_id = serializers.IntegerField(min_value=1)
    depart_at = OffsetDateTimeField()
    expected_arrival_at = OffsetDateTimeField()
    support_ends_at = OffsetDateTimeField()
    reason = serializers.CharField(max_length=1000, trim_whitespace=True)

    def validate(self, data):
        if data['from_facility_id'] == data['to_facility_id']:
            raise serializers.ValidationError({'to_facility_id': 'Cơ sở đến phải khác cơ sở đi.'})
        if not data['depart_at'] <= data['expected_arrival_at'] < data['support_ends_at']:
            raise serializers.ValidationError({'expected_arrival_at': 'Giờ đi phải trước hoặc bằng giờ đến; giờ đến phải trước giờ kết thúc.'})
        return data

    def to_internal_value(self, data):
        if not isinstance(data, Mapping):
            return super().to_internal_value(data)
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError({key: 'Trường không được hỗ trợ.' for key in sorted(unknown)})
        return super().to_internal_value(data)


class SupportCreateSerializer(SupportFieldsSerializer):
    request_id = serializers.RegexField(r'^[A-Za-z0-9_.:-]+$', max_length=100)
    schedule_id = serializers.IntegerField(min_value=1)


class SupportUpdateSerializer(SupportFieldsSerializer):
    expected_updated_at = OffsetDateTimeField()


class SupportCancelSerializer(serializers.Serializer):
    expected_updated_at = OffsetDateTimeField()
    reason = serializers.CharField(max_length=1000, trim_whitespace=True)


class DemoScheduleCreateSerializer(serializers.Serializer):
    employee_id = serializers.IntegerField(min_value=1)
    work_date = serializers.DateField()
