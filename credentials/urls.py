from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    CredentialTypeViewSet,
    CredentialRequestViewSet,
    RequirementDocumentViewSet,
    StudentClearanceViewSet,
    PaymentViewSet,
    PredictTurnaroundView,
    AdminDailyForecastView,
    AdminMonthlyWorkloadView,
    MLHealthStatusView
)

router = DefaultRouter()
router.register(r'credential-types', CredentialTypeViewSet, basename='credentialtype')
router.register(r'requests', CredentialRequestViewSet, basename='credentialrequest')
router.register(
    r'documents', RequirementDocumentViewSet, basename='requirementdocument'
)
router.register(
    r'clearances', StudentClearanceViewSet, basename='studentclearance'
)
router.register(r'payments', PaymentViewSet, basename='payment')

urlpatterns = [
    # ML Prediction & Forecasting Endpoints
    path(
        'credentials/predict-turnaround/',
        PredictTurnaroundView.as_view(),
        name='predict-turnaround'
    ),
    path(
        'credentials/forecast/daily/',
        AdminDailyForecastView.as_view(),
        name='admin-daily-forecast'
    ),
    path(
        'credentials/forecast/monthly-workload/',
        AdminMonthlyWorkloadView.as_view(),
        name='admin-monthly-workload'
    ),
    path(
        'credentials/ml-health/',
        MLHealthStatusView.as_view(),
        name='ml-health-status'
    ),
    path('', include(router.urls)),
]
