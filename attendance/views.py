from django.conf import settings
from django.db import connection, DatabaseError
from django.db.models import Q
from rest_framework import generics
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import (Employee, Facility, WorkSchedule, SupportAssignment,
                     AttendanceScan, AttendanceAlert, AttendanceRequest)
from .serializers import (EmployeeSerializer, FacilitySerializer,
    ScheduleSerializer, SupportSerializer, ScanSerializer, AlertSerializer,
    RequestSerializer, QuerySerializer, DemoScanSerializer, QrIssueSerializer, QrScanSerializer,
    VerifyAlertSerializer, ReviewRequestSerializer, SupportCreateSerializer, SupportUpdateSerializer, SupportCancelSerializer, DemoScheduleCreateSerializer)
from .services import day_bounds, record_demo_scan, issue_qr, verify_alert, review_request
from .support_services import create_assignment, update_assignment, cancel_assignment, create_demo_schedule


class HealthView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({'status': 'ok', 'service': 'worktrack-api'})


class DatabaseHealthView(APIView):
    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
                cursor.fetchone()
        except DatabaseError:
            return Response({'status': 'unavailable'}, status=503)
        return Response({'status': 'ok', 'database': 'mysql'})


class FacilityList(generics.ListAPIView):
    serializer_class = FacilitySerializer
    queryset = Facility.objects.order_by('code')


class FilteredList(generics.ListAPIView):
    model = None
    employee_path = 'employee'
    facility_path = 'facility_id'
    date_path = 'work_date'

    def get_queryset(self):
        params = QuerySerializer(data=self.request.query_params)
        params.is_valid(raise_exception=True)
        data = params.validated_data
        queryset = self.model.objects.all()
        if data.get('employee_id'):
            queryset = queryset.filter(**{f'{self.employee_path}__id': data['employee_id']})
        if data.get('facility_id'):
            queryset = queryset.filter(**{self.facility_path: data['facility_id']})
        if data.get('date'):
            if self.model is AttendanceRequest:
                start, end = day_bounds(data['date'])
                queryset = queryset.filter(Q(schedule__work_date=data['date']) | Q(
                    schedule__isnull=True, proposed_occurred_at__gte=start, proposed_occurred_at__lt=end))
            elif self.date_path == 'occurred_at':
                start, end = day_bounds(data['date'])
                queryset = queryset.filter(occurred_at__gte=start, occurred_at__lt=end)
            else:
                queryset = queryset.filter(**{self.date_path: data['date']})
        if data.get('status') and self.model is not AttendanceScan:
            queryset = queryset.filter(status=data['status'])
        if data.get('alert_id') and self.model is AttendanceScan:
            queryset = queryset.filter(alert_id=data['alert_id'])
        if data.get('outcome') and self.model is AttendanceScan:
            queryset = queryset.filter(outcome=data['outcome'])
        return queryset.order_by('-id')


class EmployeeList(generics.ListAPIView):
    serializer_class = EmployeeSerializer

    def get_queryset(self):
        params = QuerySerializer(data=self.request.query_params)
        params.is_valid(raise_exception=True)
        data = params.validated_data
        queryset = Employee.objects.select_related('home_facility')
        if data.get('facility_id'):
            queryset = queryset.filter(home_facility_id=data['facility_id'])
        if data.get('status'):
            queryset = queryset.filter(status=data['status'])
        if data.get('search'):
            queryset = queryset.filter(Q(full_name__icontains=data['search']) | Q(employee_code__icontains=data['search']))
        return queryset.order_by('employee_code')


class EmployeeDetail(generics.RetrieveAPIView):
    serializer_class = EmployeeSerializer

    def get_queryset(self):
        return Employee.objects.select_related('home_facility')


class ScheduleList(FilteredList):
    model = WorkSchedule
    serializer_class = ScheduleSerializer
    facility_path = 'owner_facility_id'


class SupportList(FilteredList):
    model = SupportAssignment
    serializer_class = SupportSerializer
    employee_path = 'schedule__employee'
    facility_path = 'to_facility_id'
    date_path = 'schedule__work_date'


class ScanList(FilteredList):
    model = AttendanceScan
    serializer_class = ScanSerializer
    date_path = 'occurred_at'

    def get_queryset(self):
        return super().get_queryset().select_related('employee', 'facility')


class AlertList(FilteredList):
    model = AttendanceAlert
    serializer_class = AlertSerializer


class RequestList(FilteredList):
    model = AttendanceRequest
    serializer_class = RequestSerializer
    facility_path = 'proposed_facility_id'
    date_path = 'schedule__work_date'


class DemoScanView(APIView):
    def post(self, request):
        if not settings.DEMO_MODE:
            raise PermissionDenied('Bật DEMO_MODE để quét mô phỏng.')
        serializer = DemoScanSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        scan, replayed = record_demo_scan(serializer.validated_data)
        return Response({'scan': ScanSerializer(scan).data, 'replayed': replayed,
                         'message': scan.decision_snapshot['message'],
                         'warnings': scan.decision_snapshot['warnings']}, status=200 if replayed else 201)


class QrIssueView(APIView):
    def post(self, request):
        if not settings.DEMO_MODE:
            raise PermissionDenied('Bật DEMO_MODE để phát QR mô phỏng.')
        serializer = QrIssueSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(issue_qr(**serializer.validated_data), status=201)


class QrScanView(APIView):
    def post(self, request):
        if not settings.DEMO_MODE:
            raise PermissionDenied('Bật DEMO_MODE để quét QR mô phỏng.')
        serializer = QrScanSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        scan, replayed = record_demo_scan(serializer.validated_data, channel='QR')
        return Response({'scan': ScanSerializer(scan).data, 'replayed': replayed,
                         'message': scan.decision_snapshot['message'],
                         'warnings': scan.decision_snapshot['warnings']}, status=200 if replayed else 201)


class VerifyAlertView(APIView):
    def post(self, request, pk):
        if not settings.DEMO_MODE:
            raise PermissionDenied('Bật DEMO_MODE để xác minh cảnh báo.')
        serializer = VerifyAlertSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        alert, replayed = verify_alert(pk, **serializer.validated_data)
        return Response({'alert': AlertSerializer(alert).data, 'replayed': replayed})


class ReviewRequestView(APIView):
    def post(self, request, pk):
        if not settings.DEMO_MODE:
            raise PermissionDenied('Bật DEMO_MODE để xử lý giải trình.')
        serializer = ReviewRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item, replayed = review_request(pk, **serializer.validated_data)
        return Response({'request': RequestSerializer(item).data, 'replayed': replayed})


class SupportCreateView(APIView):
    def post(self, request):
        if not settings.DEMO_MODE:
            raise PermissionDenied('Bật DEMO_MODE để tạo phân công mô phỏng.')
        serializer = SupportCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item, replayed = create_assignment(serializer.validated_data)
        return Response({'assignment': SupportSerializer(item).data, 'replayed': replayed}, status=200 if replayed else 201)


class SupportUpdateView(APIView):
    def put(self, request, pk):
        if not settings.DEMO_MODE:
            raise PermissionDenied('Bật DEMO_MODE để sửa phân công mô phỏng.')
        serializer = SupportUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = update_assignment(pk, serializer.validated_data)
        return Response({'assignment': SupportSerializer(item).data})


class SupportCancelView(APIView):
    def post(self, request, pk):
        if not settings.DEMO_MODE:
            raise PermissionDenied('Bật DEMO_MODE để hủy phân công mô phỏng.')
        serializer = SupportCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = cancel_assignment(pk, serializer.validated_data)
        return Response({'assignment': SupportSerializer(item).data})


class DemoScheduleCreateView(APIView):
    def post(self, request):
        if not settings.DEMO_MODE:
            raise PermissionDenied('Bật DEMO_MODE để tạo ca mô phỏng.')
        serializer = DemoScheduleCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item, replayed = create_demo_schedule(**serializer.validated_data)
        return Response({'schedule': ScheduleSerializer(item).data, 'replayed': replayed}, status=200 if replayed else 201)
