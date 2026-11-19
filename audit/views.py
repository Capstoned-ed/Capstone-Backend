from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import AuditLog


ACTION_LABELS = {
    'USER_CREATED': 'Account Provisioned',
    'USER_UPDATED': 'Account Details & Role Permissions Updated',
    'USER_DEACTIVATED': 'Account Deactivated (Status: Inactive)',
    'CREDENTIAL_TYPE_CREATED': 'Credential Type Created',
    'CREDENTIAL_TYPE_UPDATED': 'Credential Type Updated',
    'CREDENTIAL_TYPE_DEACTIVATED': 'Credential Type Deactivated',
    'REQUEST_CREATED': 'Credential Request Created',
    'PAYMENT_SUBMITTED': 'Payment Submitted',
    'DOCUMENT_UPLOADED': 'Requirement Document Uploaded',
    'CLEARANCE_SUBMITTED': 'Clearance Submitted',
}


def _format_audit_log(log, user):
    new_state = log.new_state if isinstance(log.new_state, dict) else {}
    prev_state = (
        log.previous_state if isinstance(log.previous_state, dict) else {}
    )
    meta = log.metadata if isinstance(log.metadata, dict) else {}

    target_name = (
        new_state.get('full_name')
        or new_state.get('username')
        or prev_state.get('username')
        or new_state.get('name')
        or meta.get('student_name')
        or f"{log.object_type} #{log.object_id}"
    )
    target_id = (
        new_state.get('username')
        or prev_state.get('username')
        or new_state.get('tracking_number')
        or new_state.get('code')
        or str(log.object_id)
    )
    role_or_doc = (
        new_state.get('role')
        or prev_state.get('role')
        or new_state.get('credential_type')
        or log.object_type
    )

    action_label = ACTION_LABELS.get(log.action)
    if not action_label:
        action_label = log.action.replace('_', ' ').title()
    elif log.action == 'USER_CREATED' and new_state.get('role'):
        role_upper = str(new_state['role']).upper()
        action_label = f"Account Provisioned ({role_upper})"

    if log.action == 'USER_DEACTIVATED' or new_state.get('is_active') is False:
        item_status = 'Inactive'
    elif new_state.get('is_active') is True:
        item_status = 'Active'
    elif new_state.get('status'):
        item_status = str(new_state['status']).replace('_', ' ').title()
    else:
        item_status = 'Recorded'

    if user:
        actor_name = (getattr(user, 'username', '') or '').lower()
        actor_id = str(getattr(user, 'id', user))
    else:
        actor_name = (
            meta.get('actor_username')
            or meta.get('actor_name')
            or 'Deleted User'
        )
        actor_id = str(meta.get('actor_id') or 'deleted')

    return {
        'id': f"audit-{log.id}",
        'actor': actor_name,
        'actorId': actor_id,
        'targetName': target_name,
        'targetId': target_id,
        'trackingNumber': target_id,
        'role': new_state.get('role') or prev_state.get('role'),
        'documentType': role_or_doc,
        'action': action_label,
        'timestamp': log.timestamp.isoformat(),
        'status': item_status,
        'source': 'backend',
    }


class MyAuditLogListView(APIView):
    """
    Returns audit log entries performed by the currently authenticated user.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        logs = (
            AuditLog.objects
            .filter(actor=request.user)
            .order_by('-timestamp')[:100]
        )
        data = [_format_audit_log(log, request.user) for log in logs]
        return Response(data, status=status.HTTP_200_OK)


class AuditLogListView(APIView):
    """
    Returns audit log entries across the system for administrators.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if getattr(request.user, 'role', None) != 'admin':
            return Response(
                {"detail": "Only administrators can view system audit logs."},
                status=status.HTTP_403_FORBIDDEN
            )

        qs = AuditLog.objects.select_related('actor').order_by('-timestamp')
        action = request.query_params.get('action')
        if action:
            qs = qs.filter(action__iexact=action)
        actor_id = request.query_params.get('actor_id')
        if actor_id:
            qs = qs.filter(actor_id=actor_id)

        try:
            limit = min(int(request.query_params.get('page_size', 100)), 200)
        except ValueError:
            limit = 100

        logs = qs[:limit]
        data = [
            _format_audit_log(log, log.actor)
            for log in logs
        ]
        return Response(data, status=status.HTTP_200_OK)
