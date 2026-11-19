from accounts.models import Role
from ..models import Payment


def list_payments(user):
    """
    Returns payments filtered with student ownership isolation.
    """
    qs = Payment.objects.select_related(
        'request__user'
    ).order_by('-uploaded_at')

    if (
        getattr(user, 'is_authenticated', False)
        and getattr(user, 'role', None) == Role.STUDENT
    ):
        return qs.filter(request__user=user)

    return qs
