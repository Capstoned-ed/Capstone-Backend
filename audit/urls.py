from django.urls import path
from .views import MyAuditLogListView, AuditLogListView

urlpatterns = [
    path('audit/', AuditLogListView.as_view(), name='audit-logs'),
    path('audit/my-logs/', MyAuditLogListView.as_view(), name='my-audit-logs'),
]
