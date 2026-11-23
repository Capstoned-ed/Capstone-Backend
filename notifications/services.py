import logging
import threading
from datetime import timedelta
from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from .models import Notification, NotificationEvent

logger = logging.getLogger(__name__)


def send_request_notification(
    user,
    title,
    message,
    reference_id=None,
    send_email=True,
    event_type=NotificationEvent.REQUEST_STATUS_CHANGED,
    related_object_type='CredentialRequest',
):
    """
    Centralized notification dispatcher:
    1. Creates exactly one in-app Notification record (idempotent / deduplicated).
    2. Asynchronously sends an email notification via Django SMTP if user has email.
    """
    rel_id_str = str(reference_id) if reference_id is not None else None
    notification = NotificationService.create_notification(
        recipient=user,
        event_type=event_type,
        message=message,
        related_object_type=related_object_type,
        related_object_id=rel_id_str,
    )

    user_email = getattr(user, 'email', '') or ''
    if send_email and user_email and '@' in user_email:
        def _send_email_async():
            try:
                name = (
                    getattr(user, 'first_name', '')
                    or getattr(user, 'username', 'Student')
                )
                subject = f"RegQuest - {title}"
                ref_info = f"Tracking Number: {rel_id_str}\n\n" if rel_id_str else ""
                body = (
                    f"Hello {name},\n\n"
                    f"{message}\n\n"
                    f"{ref_info}"
                    "Please check your RegQuest dashboard for real-time updates.\n\n"
                    "— RegQuest Academic Credential Management System"
                )
                send_mail(
                    subject=subject,
                    message=body,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[user_email],
                    fail_silently=False,
                )
            except Exception as exc:
                logger.error(
                    "Failed to send email notification to %s for %s: %s",
                    user_email,
                    rel_id_str or title,
                    exc,
                    exc_info=True,
                )

        try:
            email_thread = threading.Thread(target=_send_email_async, daemon=True)
            email_thread.start()
        except Exception as thread_exc:
            logger.error("Could not spawn email notification thread: %s", thread_exc)

    return notification


class NotificationService:
    send_request_notification = staticmethod(send_request_notification)

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
        Creates a notification synchronously with strict idempotency / deduplication.
        Prevents duplicate notifications for the same recipient, event, and reference ID
        within a 60-second window.
        """
        rel_id_str = str(related_object_id) if related_object_id is not None else None
        cutoff = timezone.now() - timedelta(seconds=60)

        # Idempotency guard: prevent duplicate notifications
        qs = Notification.objects.filter(
            user=recipient,
            event_type=event_type,
            created_at__gte=cutoff,
        )
        if rel_id_str:
            existing = qs.filter(related_object_id=rel_id_str).first()
            if existing:
                return existing
        else:
            existing = qs.filter(message=message).first()
            if existing:
                return existing

        notification = Notification(
            user=recipient,
            event_type=event_type,
            message=message,
            related_object_type=related_object_type,
            related_object_id=rel_id_str,
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
