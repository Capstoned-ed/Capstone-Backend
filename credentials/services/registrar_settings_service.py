from django.db import transaction
from rest_framework.exceptions import PermissionDenied

from accounts.models import Role
from audit.services import AuditService
from ..models import RegistrarSettings


class RegistrarSettingsService:
    @staticmethod
    @transaction.atomic
    def update_registrar_settings(actor, data):
        """
        Updates Registrar settings including auto-approval policy and signatory info.
        Accessible exclusively to Registrar and Admin roles.
        """
        if getattr(actor, 'role', None) not in [Role.REGISTRAR, Role.ADMIN]:
            raise PermissionDenied(
                "Only Registrar or Admin can modify approval settings."
            )

        settings_obj = RegistrarSettings.get_settings()
        prev_val = settings_obj.auto_approve_requests

        auto_approve = data.get('auto_approve_requests')
        if auto_approve is None:
            auto_approve = data.get('auto_approve')

        if auto_approve is not None:
            if isinstance(auto_approve, str):
                settings_obj.auto_approve_requests = auto_approve.lower() in [
                    'true', '1', 'yes'
                ]
            else:
                settings_obj.auto_approve_requests = bool(auto_approve)

        if 'default_signatory_name' in data:
            settings_obj.default_signatory_name = str(
                data['default_signatory_name']
            ).strip()
        elif getattr(actor, 'role', None) == Role.REGISTRAR:
            full_name = (
                f"{getattr(actor, 'first_name', '')} "
                f"{getattr(actor, 'last_name', '')}"
            ).strip()
            actor_name = full_name or getattr(actor, 'username', '')
            if actor_name:
                settings_obj.default_signatory_name = actor_name

        if 'default_signatory_title' in data:
            settings_obj.default_signatory_title = str(
                data['default_signatory_title']
            ).strip()

        settings_obj.updated_by = actor
        settings_obj.save()

        AuditService.log_action(
            actor=actor,
            action='REGISTRAR_SETTINGS_UPDATED',
            object_type='RegistrarSettings',
            object_id=settings_obj.id,
            previous_state={'auto_approve_requests': prev_val},
            new_state={
                'auto_approve_requests': settings_obj.auto_approve_requests
            }
        )

        return settings_obj

