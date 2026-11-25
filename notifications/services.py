import logging
import threading
from datetime import timedelta
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
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
       Deduplicates by (user, title, reference_id) within a 60-second window,
       ignoring slight differences in message text.
    2. Asynchronously sends an email notification via Django SMTP if user has email.
    """
    rel_id_str = str(reference_id) if reference_id is not None else None
    cutoff = timezone.now() - timedelta(seconds=60)

    # 1. Unread notification deduplication guard:
    # If an unread notification already exists for (user, title, ref), refresh it
    unread_qs = Notification.objects.filter(
        user=user,
        is_read=False,
    )
    if title:
        unread_qs = unread_qs.filter(title=title)
    if rel_id_str:
        unread_qs = unread_qs.filter(related_object_id=rel_id_str)
    elif event_type:
        unread_qs = unread_qs.filter(event_type=event_type)

    existing_unread = unread_qs.first()
    if existing_unread:
        logger.info(
            "Refreshed existing unread notification for user %s, title %s, ref %s",
            getattr(user, 'username', user),
            title,
            rel_id_str,
        )
        existing_unread.message = message
        existing_unread.created_at = timezone.now()
        existing_unread.save(update_fields=['message', 'created_at'])
        return existing_unread

    # 2. Strict deduplication check by (user, title, reference_id) within 60s
    existing_qs = Notification.objects.filter(
        user=user,
        created_at__gte=cutoff,
    )
    if title:
        existing_qs = existing_qs.filter(title=title)
    if rel_id_str:
        existing_qs = existing_qs.filter(related_object_id=rel_id_str)
    elif event_type:
        existing_qs = existing_qs.filter(event_type=event_type)

    existing_notif = existing_qs.first()
    if existing_notif:
        logger.info(
            "Deduplicated notification for user %s, title %s, ref %s",
            getattr(user, 'username', user),
            title,
            rel_id_str,
        )
        return existing_notif

    notification = NotificationService.create_notification(
        recipient=user,
        title=title,
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
                clean_title = str(title or 'Notification').replace('!', '').strip()
                subject = f"USTP RegQuest - {clean_title}"

                frontend_url = getattr(
                    settings, 'FRONTEND_URL', 'https://regquest.ustp.edu.ph'
                ).rstrip('/')
                if rel_id_str:
                    tracking_url = (
                        f"{frontend_url}/student/requests?trackId={rel_id_str}"
                    )
                else:
                    tracking_url = f"{frontend_url}/student/requests"

                ref_line_text = (
                    f"Tracking Number: {rel_id_str}\n\n" if rel_id_str else ""
                )
                text_body = (
                    f"Hello {name},\n\n"
                    f"{message}\n\n"
                    f"{ref_line_text}"
                    f"Track your credential request online at: {tracking_url}\n\n"
                    "—\n"
                    "Office of the Registrar\n"
                    "University of Science and Technology of Southern "
                    "Philippines (USTP)\n"
                    "C.M. Recto Ave., Lapasan, Cagayan de Oro City, 9000\n"
                    "This is an automated transactional notification regarding your "
                    "credential request."
                )

                ref_html_badge = (
                    f'<div style="margin: 16px 0; padding: 12px 16px; '
                    f'background: #f1f5f9; border-radius: 8px; font-size: 13px; '
                    f'color: #334155;">'
                    f'<strong>Tracking Number:</strong> '
                    f'<span style="font-family: monospace; font-size: 14px; '
                    f'color: #0B0B36; font-weight: bold;">{rel_id_str}</span>'
                    f'</div>'
                    if rel_id_str else ""
                )

                html_body = (
                    '<!DOCTYPE html>\n'
                    '<html>\n'
                    '<head>\n'
                    '  <meta charset="utf-8">\n'
                    '  <meta name="viewport" content="width=device-width, '
                    'initial-scale=1.0">\n'
                    f'  <title>{clean_title}</title>\n'
                    '</head>\n'
                    '<body style="margin: 0; padding: 0; '
                    'background-color: #f8fafc; '
                    'font-family: -apple-system, BlinkMacSystemFont, '
                    '\'Segoe UI\', Roboto, Helvetica, Arial, sans-serif; '
                    'color: #1e293b;">\n'
                    '  <table width="100%" cellpadding="0" cellspacing="0" '
                    'style="background-color: #f8fafc; padding: 32px 16px;">\n'
                    '    <tr>\n'
                    '      <td align="center">\n'
                    '        <table width="100%" cellpadding="0" cellspacing="0" '
                    'style="max-width: 580px; background-color: #ffffff; '
                    'border-radius: 16px; overflow: hidden; '
                    'box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05); '
                    'border: 1px solid #e2e8f0;">\n'
                    '          <tr>\n'
                    '            <td style="background: linear-gradient(135deg, '
                    '#0B0B36 0%, #1e1b4b 100%); padding: 28px 32px; '
                    'text-align: left;">\n'
                    '              <h1 style="margin: 0; color: #ffffff; '
                    'font-size: 20px; font-weight: 800; letter-spacing: -0.5px;">'
                    'USTP RegQuest</h1>\n'
                    '              <p style="margin: 4px 0 0 0; color: #f59e0b; '
                    'font-size: 12px; font-weight: 600; text-transform: uppercase; '
                    'letter-spacing: 0.5px;">Office of the Registrar</p>\n'
                    '            </td>\n'
                    '          </tr>\n'
                    '          <tr>\n'
                    '            <td style="padding: 32px;">\n'
                    '              <p style="margin: 0 0 16px 0; font-size: 15px; '
                    'line-height: 1.5; color: #334155;">'
                    f'Hello <strong>{name}</strong>,</p>\n'
                    '              <div style="margin: 20px 0; padding: 18px 20px; '
                    'background-color: #fffbeb; border-left: 4px solid #f59e0b; '
                    'border-radius: 6px;">\n'
                    '                <p style="margin: 0; font-size: 14px; '
                    f'line-height: 1.6; color: #92400e; font-weight: 500;">\n'
                    f'                  {message}\n'
                    '                </p>\n'
                    '              </div>\n'
                    f'              {ref_html_badge}\n'
                    '              <div style="margin: 28px 0; text-align: center;">\n'
                    f'                <a href="{tracking_url}" style="display: '
                    'inline-block; background-color: #0B0B36; color: #ffffff; '
                    'text-decoration: none; font-size: 14px; font-weight: 700; '
                    'padding: 12px 28px; border-radius: 8px;">\n'
                    '                  Track Status &rarr;\n'
                    '                </a>\n'
                    '              </div>\n'
                    '              <p style="margin: 24px 0 0 0; font-size: 13px; '
                    'line-height: 1.5; color: #64748b;">\n'
                    '                You can also view all credential records, '
                    'submit payments, or download claim stubs directly from '
                    'your RegQuest student portal.\n'
                    '              </p>\n'
                    '            </td>\n'
                    '          </tr>\n'
                    '          <tr>\n'
                    '            <td style="background-color: #f8fafc; '
                    'border-top: 1px solid #e2e8f0; padding: 24px 32px; '
                    'text-align: left;">\n'
                    '              <p style="margin: 0 0 6px 0; font-size: 12px; '
                    'font-weight: 700; color: #334155;">Office of the Registrar</p>\n'
                    '              <p style="margin: 0 0 10px 0; font-size: 11px; '
                    'line-height: 1.4; color: #64748b;">\n'
                    '                University of Science and Technology of '
                    'Southern Philippines (USTP)<br>\n'
                    '                C.M. Recto Ave., Lapasan, '
                    'Cagayan de Oro City, 9000\n'
                    '              </p>\n'
                    '              <p style="margin: 0; font-size: 11px; '
                    'line-height: 1.4; color: #94a3b8;">\n'
                    '                This is an official transactional notification '
                    'sent to your registered account. Please do not reply '
                    'directly to this email.\n'
                    '              </p>\n'
                    '            </td>\n'
                    '          </tr>\n'
                    '        </table>\n'
                    '      </td>\n'
                    '    </tr>\n'
                    '  </table>\n'
                    '</body>\n'
                    '</html>'
                )

                reply_to_email = getattr(settings, 'EMAIL_HOST_USER', None)
                reply_to = (
                    [reply_to_email]
                    if reply_to_email and '@' in reply_to_email
                    else None
                )

                email_msg = EmailMultiAlternatives(
                    subject=subject,
                    body=text_body,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    to=[user_email],
                    reply_to=reply_to,
                )
                email_msg.attach_alternative(html_body, "text/html")
                email_msg.send(fail_silently=False)
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
        title='',
        related_object_type=None,
        related_object_id=None,
    ):
        """
        Creates a notification synchronously with strict idempotency / deduplication.
        1. Checks for an existing unread notification for the same recipient,
           event/title, and reference ID. If found, refreshes its message and
           timestamp to prevent duplicate unread spam.
        2. Checks for a recent notification within a 60-second window.
        """
        rel_id_str = str(related_object_id) if related_object_id is not None else None
        cutoff = timezone.now() - timedelta(seconds=60)

        # 1. Unread notification deduplication guard:
        unread_qs = Notification.objects.filter(
            user=recipient,
            is_read=False,
        )
        if title:
            unread_qs = unread_qs.filter(title=title)
        else:
            unread_qs = unread_qs.filter(event_type=event_type)

        if rel_id_str:
            existing_unread = unread_qs.filter(related_object_id=rel_id_str).first()
        else:
            existing_unread = unread_qs.filter(message=message).first()

        if existing_unread:
            existing_unread.message = message
            existing_unread.created_at = timezone.now()
            existing_unread.save(update_fields=['message', 'created_at'])
            return existing_unread

        # 2. Idempotency guard: prevent duplicate notifications within 60s
        qs = Notification.objects.filter(
            user=recipient,
            created_at__gte=cutoff,
        )
        if title:
            qs = qs.filter(title=title)
        else:
            qs = qs.filter(event_type=event_type)

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
            title=title or '',
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
