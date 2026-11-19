from accounts.models import Role
from ..models import StudentClearance


def list_student_clearances(user):
    """
    Returns student clearances filtered with student ownership isolation.
    """
    qs = StudentClearance.objects.select_related('user').order_by('-updated_at')

    if (
        getattr(user, 'is_authenticated', False)
        and getattr(user, 'role', None) == Role.STUDENT
    ):
        return qs.filter(user=user)

    return qs
