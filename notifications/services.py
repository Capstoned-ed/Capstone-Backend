from django.db import transaction
from .models import Notification


class NotificationService:
    @staticmethod
    @transaction.atomic
    def create_notification(
        *,
        recipient,
        event_type,
        message,
        related_object_type=None,
        related_object_id=None,
    ):
        """
        Creates a notification synchronously.
        """
        notification = Notification(
            user=recipient,
            event_type=event_type,
            message=message,
            related_object_type=related_object_type,
            related_object_id=related_object_id
        )
        notification.full_clean()
        notification.save()
        return notification

    @staticmethod
    @transaction.atomic
    def mark_as_read(notification):
        """
        Marks a single notification instance as read.
        """
        if not notification.is_read:
            notification.is_read = True
            notification.save(update_fields=['is_read'])
        return notification

    @staticmethod
    @transaction.atomic
    def mark_all_as_read(user):
        """
        Marks all unread notifications for the target user as read.
        """
        unread_notifications = Notification.objects.filter(
            user=user, is_read=False
        )
        return unread_notifications.update(is_read=True)
