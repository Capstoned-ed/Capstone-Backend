from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .selectors import get_user_audit_logs


class MyAuditLogListView(APIView):
    """
    Returns audit log entries performed by the currently authenticated user.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        data = get_user_audit_logs(request.user)
        return Response(data, status=status.HTTP_200_OK)
