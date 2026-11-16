from django.urls import path
from .views import MyAuditLogListView

urlpatterns = [
    path('audit/my-logs/', MyAuditLogListView.as_view(), name='my-audit-logs'),
]
