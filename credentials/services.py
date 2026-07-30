from django.db import transaction
from audit.services import AuditService
from notifications.services import NotificationService
from notifications.models import NotificationEvent
from .models import (
    CredentialType,
    CredentialRequest,
    RequirementDocument,
    StudentClearance,
    ClearanceStatus,
    RequestStatus,
    Payment,
    PaymentStatus
)
from rest_framework.exceptions import ValidationError, PermissionDenied
from django.utils import timezone
from accounts.models import Role


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
    TRANSITION_MATRIX = {
        RequestStatus.PENDING: [
            {'status': RequestStatus.REQUIREMENTS_VERIFICATION,
                'roles': [Role.STAFF, Role.ADMIN]},
            {'status': RequestStatus.CANCELLED, 'roles': [Role.STUDENT]}
        ],
        RequestStatus.REQUIREMENTS_VERIFICATION: [
            {'status': RequestStatus.PAYMENT_PENDING,
                'roles': [Role.STAFF, Role.ADMIN]},
            {'status': RequestStatus.REQUIREMENTS_REJECTED,
                'roles': [Role.STAFF, Role.ADMIN]},
            {'status': RequestStatus.REJECTED, 'roles': [Role.STAFF, Role.ADMIN]}
        ],
        RequestStatus.REQUIREMENTS_REJECTED: [
            {'status': RequestStatus.PENDING, 'roles': [Role.STUDENT]},
            {'status': RequestStatus.CANCELLED, 'roles': [Role.STUDENT]}
        ],
        RequestStatus.PAYMENT_PENDING: [
            {'status': RequestStatus.PAYMENT_VERIFIED,
                'roles': [Role.STAFF, Role.ADMIN]},
            {'status': RequestStatus.CANCELLED, 'roles': [Role.STUDENT]},
            {'status': RequestStatus.REJECTED, 'roles': [Role.STAFF, Role.ADMIN]}
        ],
        RequestStatus.PAYMENT_VERIFIED: [
            {'status': RequestStatus.PROCESSING, 'roles': [
                Role.REGISTRAR, Role.STAFF, Role.ADMIN]}
        ],
        RequestStatus.PROCESSING: [
            {'status': RequestStatus.READY_FOR_RELEASE,
                'roles': [Role.REGISTRAR, Role.ADMIN]},
            {'status': RequestStatus.REJECTED, 'roles': [Role.REGISTRAR, Role.ADMIN]}
        ],
        RequestStatus.READY_FOR_RELEASE: [
            {'status': RequestStatus.RELEASED, 'roles': [
                Role.STAFF, Role.REGISTRAR, Role.ADMIN]}
        ]
    }

    @staticmethod
    @transaction.atomic
    def create_request(actor, validated_data):
        clearance = (
            StudentClearance.objects
            .select_for_update()
            .filter(user=actor, status=ClearanceStatus.APPROVED)
            .first()
        )

        if not clearance:
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

    @staticmethod
    @transaction.atomic
    def transition_request(actor, credential_request, new_status, remarks=""):
        credential_request = (
            CredentialRequest.objects
            .select_for_update()
            .get(pk=credential_request.pk)
        )
        current_status = credential_request.status
        allowed_transitions = CredentialRequestService.TRANSITION_MATRIX.get(
            current_status, [])

        transition = next(
            (t for t in allowed_transitions if t['status'] == new_status), None)

        if not transition:
            raise ValidationError(
                f"Invalid transition from {current_status} to {new_status}.")

        if actor.role not in transition['roles']:
            raise PermissionDenied(
                "You do not have permission to perform this transition."
            )

        if new_status in [
            RequestStatus.REJECTED,
            RequestStatus.REQUIREMENTS_REJECTED
        ] and not remarks:
            raise ValidationError("Remarks are required when rejecting a request.")

        previous_state = {
            'status': credential_request.status,
            'remarks': credential_request.remarks
        }

        credential_request.status = new_status
        if remarks is not None:
            credential_request.remarks = remarks
        credential_request.save()

        new_state = {
            'status': credential_request.status,
            'remarks': credential_request.remarks
        }

        AuditService.log_action(
            actor=actor,
            action=f'REQUEST_STATUS_CHANGED_{new_status}',
            object_type='CredentialRequest',
            object_id=credential_request.id,
            previous_state=previous_state,
            new_state=new_state
        )

        if actor.role != Role.STUDENT:
            msg = (
                f"Your request ({credential_request.tracking_number}) "
                f"status changed to {new_status}."
            )
            NotificationService.create_notification(
                recipient=credential_request.user,
                event_type=NotificationEvent.REQUEST_STATUS_CHANGED,
                message=msg,
                related_object_type='CredentialRequest',
                related_object_id=str(credential_request.id)
            )

        return credential_request


class RequirementDocumentService:
    @staticmethod
    @transaction.atomic
    def upload_document(actor, validated_data):
        credential_request = validated_data['request']

        if actor.role == Role.STUDENT and credential_request.user != actor:
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


class StudentClearanceService:
    @staticmethod
    @transaction.atomic
    def submit_clearance(actor, file):
        clearance = StudentClearance.objects.filter(user=actor).first()

        if clearance:
            if clearance.status == ClearanceStatus.APPROVED:
                raise ValidationError(
                    "You cannot re-submit an already approved clearance."
                )
            clearance.file = file
            clearance.status = ClearanceStatus.PENDING
            clearance.save()
        else:
            clearance = StudentClearance.objects.create(
                user=actor, file=file, status=ClearanceStatus.PENDING
            )

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

        if status == ClearanceStatus.REJECTED and not remarks:
            raise ValidationError("Remarks are required when rejecting a clearance.")

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


class PaymentService:
    @staticmethod
    @transaction.atomic
    def submit_payment(
        actor, request, amount, receipt_image, receipt_reference_number=""
    ):
        if request.status != RequestStatus.PAYMENT_PENDING:
            raise ValidationError(
                "You can only submit an OTC payment when the request is "
                "awaiting payment."
            )

        payment = Payment.objects.create(
            request=request,
            amount=amount,
            receipt_reference_number=receipt_reference_number,
            receipt_image=receipt_image,
            status=PaymentStatus.PENDING
        )

        AuditService.log_action(
            actor=actor,
            action='PAYMENT_SUBMITTED',
            object_type='Payment',
            object_id=payment.id,
            previous_state=None,
            new_state={
                'request_id': str(request.id),
                'amount': str(amount),
                'status': payment.status
            }
        )
        return payment

    @staticmethod
    @transaction.atomic
    def verify_payment(actor, payment, action, remarks=""):
        if action not in ['VERIFY', 'REJECT']:
            raise ValidationError("Action must be VERIFY or REJECT.")

        if action == 'REJECT' and not remarks:
            raise ValidationError("Remarks are required when rejecting an OTC payment.")

        previous_state = {
            'status': payment.status,
            'remarks': payment.remarks,
            'verified_by': payment.verified_by.id if payment.verified_by else None
        }

        payment.status = (
            PaymentStatus.VERIFIED if action == 'VERIFY' else PaymentStatus.REJECTED
        )
        if remarks:
            payment.remarks = remarks
        payment.verified_by = actor
        payment.verified_at = timezone.now()
        payment.save()

        AuditService.log_action(
            actor=actor,
            action=f'PAYMENT_VERIFICATION_{action}',
            object_type='Payment',
            object_id=payment.id,
            previous_state=previous_state,
            new_state={
                'status': payment.status,
                'remarks': payment.remarks,
                'verified_by': str(actor.id)
            }
        )

        if action == 'VERIFY':
            CredentialRequestService.transition_request(
                actor=actor,
                credential_request=payment.request,
                new_status=RequestStatus.PAYMENT_VERIFIED,
                remarks="Automated transition from verified OTC payment."
            )
            NotificationService.create_notification(
                recipient=payment.request.user,
                event_type=NotificationEvent.PAYMENT_VERIFIED,
                message=(
                    f"Your OTC payment for request "
                    f"{payment.request.tracking_number} was verified."
                ),
                related_object_type='Payment',
                related_object_id=str(payment.id)
            )
        else:
            NotificationService.create_notification(
                recipient=payment.request.user,
                event_type=NotificationEvent.PAYMENT_REJECTED,
                message=(
                    f"Your OTC payment for request "
                    f"{payment.request.tracking_number} was rejected. "
                    "Please resubmit."
                ),
                related_object_type='Payment',
                related_object_id=str(payment.id)
            )

        return payment
