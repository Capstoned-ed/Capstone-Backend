from ..models import AuditLog


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


def format_audit_log(log, user):
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

    return {
        'id': f"audit-{log.id}",
        'actor': (user.username or '').lower(),
        'actorId': str(user.id),
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


def get_user_audit_logs(user, limit=100):
    """
    Returns formatted audit log entries performed by the given user.
    """
    logs = (
        AuditLog.objects
        .filter(actor=user)
        .order_by('-timestamp')[:limit]
    )
    return [format_audit_log(log, user) for log in logs]

