from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema
from .models import Notification
from .serializers import NotificationSerializer


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint that allows users to view their notifications.
    Supports marking single or all notifications as read.
    """
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # Strict data isolation: Users can only see their own notifications
        return Notification.objects.filter(user=self.request.user)

    @extend_schema(responses={200: NotificationSerializer})
    @action(detail=True, methods=['patch'], url_path='read')
    def mark_read(self, request, pk=None):
        """
        Mark a single notification as read.
        """
        notification = self.get_object()
        if not notification.is_read:
            notification.is_read = True
            notification.save(update_fields=['is_read'])
        return Response(NotificationSerializer(notification).data)

    @extend_schema(responses={200: dict})
    @action(detail=False, methods=['post'], url_path='mark_all_read')
    def mark_all_read(self, request):
        """
        Mark all unread notifications for the current user as read.
        """
        qs = self.get_queryset().filter(is_read=False)
        count = qs.update(is_read=True)
        return Response(
            {"status": "success", "updated_count": count},
            status=status.HTTP_200_OK
        )
