from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.pagination import PageNumberPagination
from drf_spectacular.utils import extend_schema

from .serializers import NotificationSerializer
from .selectors import get_user_notifications
from .services import NotificationService


class NotificationPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint that allows users to view their notifications.
    Supports marking single or all notifications as read.
    """
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = NotificationPagination

    def get_queryset(self):
        return get_user_notifications(self.request.user)

    @extend_schema(responses={200: NotificationSerializer})
    @action(detail=True, methods=['patch'], url_path='read')
    def mark_read(self, request, pk=None):
        """
        Mark a single notification as read.
        """
        notification = self.get_object()
        updated = NotificationService.mark_as_read(notification)
        return Response(NotificationSerializer(updated).data)

    @extend_schema(responses={200: dict})
    @action(detail=False, methods=['post'], url_path='mark_all_read')
    def mark_all_read(self, request):
        """
        Mark all unread notifications for the current user as read.
        """
        count = NotificationService.mark_all_as_read(request.user)
        return Response(
            {"status": "success", "updated_count": count},
            status=status.HTTP_200_OK
        )
