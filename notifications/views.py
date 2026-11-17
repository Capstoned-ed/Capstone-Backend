from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.pagination import PageNumberPagination
from drf_spectacular.utils import extend_schema
from accounts.models import Role
from .models import Notification, NotificationEvent
from .serializers import NotificationSerializer


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
        # Prevent crash during OpenAPI schema generation with AnonymousUser
        if not getattr(self.request.user, 'is_authenticated', False):
            return Notification.objects.none()

        # Strict data isolation: Users can only see their own notifications
        qs = Notification.objects.filter(user=self.request.user)
        if getattr(self.request.user, 'role', None) == Role.ADMIN:
            qs = qs.exclude(
                event_type__in=[
                    NotificationEvent.REQUEST_CREATED,
                    NotificationEvent.CLEARANCE_SUBMITTED,
                    NotificationEvent.PAYMENT_SUBMITTED,
                ]
            )
        return qs

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
