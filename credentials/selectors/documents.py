from accounts.models import Role
from ..models import RequirementDocument


def list_requirement_documents(user):
    """
    Returns requirement documents filtered with student ownership isolation.
    """
    qs = RequirementDocument.objects.select_related(
        'request__user'
    ).order_by('-uploaded_at')

    if (
        getattr(user, 'is_authenticated', False)
        and getattr(user, 'role', None) == Role.STUDENT
    ):
        return qs.filter(request__user=user)

    return qs
