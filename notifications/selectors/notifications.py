from accounts.models import Role
from ..models import Notification, NotificationEvent


def get_user_notifications(user):
    """
    Returns notifications for the given user with strict role-based data isolation.
    Admins are isolated from raw student lifecycle events.
    """
    if not getattr(user, 'is_authenticated', False):
        return Notification.objects.none()

    qs = Notification.objects.filter(user=user)
    if getattr(user, 'role', None) == Role.ADMIN:
        qs = qs.exclude(
            event_type__in=[
                NotificationEvent.REQUEST_CREATED,
                NotificationEvent.CLEARANCE_SUBMITTED,
                NotificationEvent.PAYMENT_SUBMITTED,
            ]
        )
    return qs

