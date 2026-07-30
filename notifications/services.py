from .models import Notification


class NotificationService:
    @staticmethod
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
