from django.urls import path
from . import views

urlpatterns = [
    path('health/', views.HealthView.as_view()),
    path('health/database/', views.DatabaseHealthView.as_view()),
    path('facilities/', views.FacilityList.as_view()),
    path('employees/', views.EmployeeList.as_view()),
    path('employees/<int:pk>/', views.EmployeeDetail.as_view()),
    path('schedules/', views.ScheduleList.as_view()),
    path('schedules/demo-create/', views.DemoScheduleCreateView.as_view()),
    path('schedules/defaults/', views.DefaultSchedulesView.as_view()),
    path('support-assignments/', views.SupportList.as_view()),
    path('support-assignments/create/', views.SupportCreateView.as_view()),
    path('support-assignments/<int:pk>/', views.SupportUpdateView.as_view()),
    path('support-assignments/<int:pk>/cancel/', views.SupportCancelView.as_view()),
    path('scans/', views.ScanList.as_view()),
    path('scans/demo/', views.DemoScanView.as_view()),
    path('qr/challenges/', views.QrIssueView.as_view()),
    path('qr/scans/', views.QrScanView.as_view()),
    path('alerts/', views.AlertList.as_view()),
    path('alerts/<int:pk>/verify/', views.VerifyAlertView.as_view()),
    path('requests/', views.RequestList.as_view()),
    path('requests/add-event/', views.AddEventRequestView.as_view()),
    path('requests/<int:pk>/review/', views.ReviewRequestView.as_view()),
    path('work-days/', views.WorkDayView.as_view()),
    path('work-months/', views.WorkMonthView.as_view()),
]
