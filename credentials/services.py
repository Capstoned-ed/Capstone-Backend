from django.db import transaction
from audit.services import AuditService
from notifications.services import NotificationService
from notifications.models import NotificationEvent
from .models import (
    CredentialType,
    CredentialRequest,
    RequirementDocument,
    StudentClearance,
    ClearanceStatus
)
from rest_framework.exceptions import ValidationError
from django.utils import timezone


class CredentialTypeService:
    @staticmethod
    @transaction.atomic
    def create_type(actor, validated_data):
        credential_type = CredentialType.objects.create(**validated_data)

        AuditService.log_action(
            actor=actor,
            action='CREDENTIAL_TYPE_CREATED',
            object_type='CredentialType',
            object_id=credential_type.id,
            previous_state=None,
            new_state={
                'code': credential_type.code,
                'name': credential_type.name,
                'price': str(credential_type.price),
                'processing_days': credential_type.processing_days,
                'is_active': credential_type.is_active
            }
        )
        return credential_type

    @staticmethod
    @transaction.atomic
    def update_type(actor, credential_type, validated_data):
        previous_state = {
            'code': credential_type.code,
            'name': credential_type.name,
            'description': credential_type.description,
            'price': str(credential_type.price),
            'processing_days': credential_type.processing_days,
            'is_active': credential_type.is_active
        }

        for attr, value in validated_data.items():
            setattr(credential_type, attr, value)

        credential_type.save()

        new_state = {
            'code': credential_type.code,
            'name': credential_type.name,
            'description': credential_type.description,
            'price': str(credential_type.price),
            'processing_days': credential_type.processing_days,
            'is_active': credential_type.is_active
        }

        if previous_state != new_state:
            AuditService.log_action(
                actor=actor,
                action='CREDENTIAL_TYPE_UPDATED',
                object_type='CredentialType',
                object_id=credential_type.id,
                previous_state=previous_state,
                new_state=new_state
            )

        return credential_type

    @staticmethod
    @transaction.atomic
    def deactivate_type(actor, credential_type):
        previous_state = {'is_active': credential_type.is_active}
        credential_type.is_active = False
        credential_type.save(update_fields=['is_active'])

        AuditService.log_action(
            actor=actor,
            action='CREDENTIAL_TYPE_DEACTIVATED',
            object_type='CredentialType',
            object_id=credential_type.id,
            previous_state=previous_state,
            new_state={'is_active': False}
        )
        return credential_type


class CredentialRequestService:
    @staticmethod
    @transaction.atomic
    def create_request(actor, validated_data):
        has_clearance = StudentClearance.objects.filter(
            user=actor, status=ClearanceStatus.APPROVED
        ).exists()

        if not has_clearance:
            raise ValidationError(
                "You must have an APPROVED clearance to create a request."
            )

        validated_data['user'] = actor
        credential_request = CredentialRequest.objects.create(**validated_data)

        AuditService.log_action(
            actor=actor,
            action='REQUEST_CREATED',
            object_type='CredentialRequest',
            object_id=credential_request.id,
            previous_state=None,
            new_state={
                'tracking_number': credential_request.tracking_number,
                'status': credential_request.status,
                'credential_type': credential_request.credential_type.code,
                'remarks': credential_request.remarks
            }
        )

        msg = (
            f"Your credential request ({credential_request.tracking_number}) "
            "has been created."
        )
        NotificationService.create_notification(
            recipient=actor,
            event_type=NotificationEvent.REQUEST_CREATED,
            message=msg,
            related_object_type='CredentialRequest',
            related_object_id=str(credential_request.id)
        )

        return credential_request


class RequirementDocumentService:
    @staticmethod
    @transaction.atomic
    def upload_document(actor, validated_data):
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


class StudentClearanceService:
    @staticmethod
    @transaction.atomic
    def submit_clearance(actor, file):
        clearance, created = StudentClearance.objects.get_or_create(
            user=actor,
            defaults={'file': file, 'status': ClearanceStatus.PENDING}
        )

        if not created:
            clearance.file = file
            clearance.status = ClearanceStatus.PENDING
            clearance.save()

        AuditService.log_action(
            actor=actor,
            action='CLEARANCE_SUBMITTED',
            object_type='StudentClearance',
            object_id=clearance.id,
            previous_state=None,
            new_state={
                'user': str(actor.id),
                'status': clearance.status,
                'file_name': clearance.file.name
            }
        )
        return clearance

    @staticmethod
    @transaction.atomic
    def review_clearance(actor, clearance, status, remarks=""):
        if status not in [ClearanceStatus.APPROVED, ClearanceStatus.REJECTED]:
            raise ValidationError("Invalid clearance status.")

        if clearance.status != ClearanceStatus.PENDING:
            raise ValidationError("Only PENDING clearances can be reviewed.")

        previous_state = {
            'status': clearance.status,
            'remarks': clearance.remarks
        }

        clearance.status = status
        clearance.remarks = remarks
        clearance.reviewed_by = actor
        clearance.reviewed_at = timezone.now()
        clearance.save()

        new_state = {
            'status': clearance.status,
            'remarks': clearance.remarks,
            'reviewed_by': str(actor.id)
        }

        audit_action = (
            'CLEARANCE_APPROVED' if status == ClearanceStatus.APPROVED
            else 'CLEARANCE_REJECTED'
        )

        AuditService.log_action(
            actor=actor,
            action=audit_action,
            object_type='StudentClearance',
            object_id=clearance.id,
            previous_state=previous_state,
            new_state=new_state
        )

        notification_event = (
            NotificationEvent.CLEARANCE_APPROVED
            if status == ClearanceStatus.APPROVED
            else NotificationEvent.CLEARANCE_REJECTED
        )
        msg = f"Your student clearance has been {status.lower()}."

        NotificationService.create_notification(
            recipient=clearance.user,
            event_type=notification_event,
            message=msg,
            related_object_type='StudentClearance',
            related_object_id=str(clearance.id)
        )

        return clearance
