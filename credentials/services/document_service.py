from django.db import transaction
from rest_framework.exceptions import PermissionDenied

from accounts.models import Role
from audit.services import AuditService
from ..models import RequirementDocument


class RequirementDocumentService:
    @staticmethod
    @transaction.atomic
    def upload_document(actor, validated_data):
        credential_request = validated_data['request']

        if (
            getattr(actor, 'role', None) == Role.STUDENT
            and credential_request.user != actor
        ):
            raise PermissionDenied(
                "You can only upload documents to your own credential requests."
            )

        document = RequirementDocument.objects.create(**validated_data)

        AuditService.log_action(
            actor=actor,
            action='DOCUMENT_UPLOADED',
            object_type='RequirementDocument',
            object_id=document.id,
            previous_state=None,
            new_state={
                'request': str(document.request.id),
                'document_type': document.document_type,
                'file_name': document.file.name
            }
        )
        return document

