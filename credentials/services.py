from django.contrib.auth import get_user_model
from django.db import transaction, models
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

User = get_user_model()


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
                'doc_code': credential_type.doc_code,
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
            'doc_code': credential_type.doc_code,
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
            'doc_code': credential_type.doc_code,
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
            {'status': RequestStatus.PAYMENT_PENDING,
                'roles': [Role.STAFF, Role.ADMIN]},
            {'status': RequestStatus.REJECTED,
                'roles': [Role.STAFF, Role.ADMIN]},
            {'status': RequestStatus.CANCELLED, 'roles': [Role.STUDENT]}
        ],
        RequestStatus.REQUIREMENTS_VERIFICATION: [
            {'status': RequestStatus.PAYMENT_PENDING,
                'roles': [Role.STAFF, Role.ADMIN]},
            {'status': RequestStatus.REQUIREMENTS_REJECTED,
                'roles': [Role.STAFF, Role.ADMIN]},
            {'status': RequestStatus.REJECTED,
                'roles': [Role.STAFF, Role.ADMIN]}
        ],
        RequestStatus.REQUIREMENTS_REJECTED: [
            {'status': RequestStatus.PENDING, 'roles': [Role.STUDENT]},
            {'status': RequestStatus.CANCELLED, 'roles': [Role.STUDENT]}
        ],
        RequestStatus.PAYMENT_PENDING: [
            {'status': RequestStatus.PAYMENT_VERIFIED,
                'roles': [Role.STAFF, Role.ADMIN]},
            {'status': RequestStatus.CANCELLED, 'roles': [Role.STUDENT]},
            {'status': RequestStatus.REJECTED,
                'roles': [Role.STAFF, Role.ADMIN]}
        ],
        RequestStatus.PAYMENT_VERIFIED: [
            {'status': RequestStatus.PROCESSING, 'roles': [
                Role.REGISTRAR, Role.STAFF, Role.ADMIN
            ]},
            {'status': RequestStatus.REJECTED, 'roles': [
                Role.REGISTRAR, Role.ADMIN
            ]}
        ],
        RequestStatus.PROCESSING: [
            {'status': RequestStatus.READY_FOR_RELEASE, 'roles': [
                Role.REGISTRAR, Role.ADMIN
            ]},
            {'status': RequestStatus.REJECTED, 'roles': [
                Role.REGISTRAR, Role.ADMIN
            ]}
        ],
        RequestStatus.READY_FOR_RELEASE: [
            {'status': RequestStatus.RELEASED, 'roles': [
                Role.REGISTRAR, Role.ADMIN, Role.STAFF
            ]},
            {'status': RequestStatus.REJECTED, 'roles': [
                Role.REGISTRAR, Role.ADMIN
            ]}
        ],
        RequestStatus.RELEASED: [],
        RequestStatus.REJECTED: [],
        RequestStatus.CANCELLED: []
    }

    @staticmethod
    @transaction.atomic
    def create_request(actor, validated_data):
        clearance = (
            StudentClearance.objects
            .select_for_update()
            .filter(user=actor)
            .first()
        )

        if not clearance:
            raise ValidationError(
                "You must submit a clearance document before creating a request."
            )

        if clearance.status == ClearanceStatus.REJECTED:
            raise ValidationError(
                "Your previous clearance was rejected. Please re-upload "
                "a valid clearance before requesting a document."
            )

        validated_data['user'] = actor
        custom_doc_code = validated_data.pop('custom_doc_code', None)
        credential_request = CredentialRequest(**validated_data)
        if custom_doc_code:
            credential_request._custom_doc_code = custom_doc_code
        credential_request.save()

        AuditService.log_action(
            actor=actor,
            action='REQUEST_CREATED',
            object_type='CredentialRequest',
            object_id=credential_request.id,
            previous_state=None,
            new_state={
                'tracking_number': credential_request.tracking_number,
                'course': credential_request.course,
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
    def transition_request(
        actor, credential_request, new_status, remarks="",
        assigned_staff=None, in_process_queue=None
    ):
        credential_request = (
            CredentialRequest.objects
            .select_for_update()
            .get(pk=credential_request.pk)
        )
        current_status = credential_request.status

        # Normalize status to canonical RequestStatus enum
        status_map = {
            'PENDING': RequestStatus.PENDING,
            'REQUIREMENTS_VERIFICATION': RequestStatus.REQUIREMENTS_VERIFICATION,
            'REQUIREMENTS_REJECTED': RequestStatus.REQUIREMENTS_REJECTED,
            'PAYMENT_PENDING': RequestStatus.PAYMENT_PENDING,
            'PAYMENT_VERIFIED': RequestStatus.PAYMENT_VERIFIED,
            'PROCESSING': RequestStatus.PROCESSING,
            'READY_FOR_RELEASE': RequestStatus.READY_FOR_RELEASE,
            'RELEASED': RequestStatus.RELEASED,
            'REJECTED': RequestStatus.REJECTED,
            'CANCELLED': RequestStatus.CANCELLED,
            'FOR PAYMENT': RequestStatus.PAYMENT_PENDING,
            'FOR_PAYMENT': RequestStatus.PAYMENT_PENDING,
            'FOR PROCESSING': RequestStatus.PAYMENT_VERIFIED,
            'FOR_PROCESSING': RequestStatus.PAYMENT_VERIFIED,
            'READY FOR PICKUP': RequestStatus.READY_FOR_RELEASE,
            'READY_FOR_PICKUP': RequestStatus.READY_FOR_RELEASE,
            'READY FOR RELEASE': RequestStatus.READY_FOR_RELEASE,
            'RELEASING': RequestStatus.READY_FOR_RELEASE,
            'CLAIMED': RequestStatus.RELEASED,
            'COMPLETED': RequestStatus.RELEASED,
        }
        clean_key = str(new_status).strip().upper().replace('-', '_')
        canonical_status = status_map.get(clean_key, clean_key)

        if clean_key in ['RESTORE', 'REOPEN']:
            return CredentialRequestService.restore_request(
                actor=actor,
                credential_request=credential_request,
                remarks=remarks
            )

        # Handle staff assignment if provided
        if assigned_staff is not None:
            if isinstance(assigned_staff, User):
                credential_request.assigned_staff = assigned_staff
                credential_request.in_process_queue = True
            elif isinstance(assigned_staff, (str, int)) and str(assigned_staff).strip():
                s_ident = str(assigned_staff).strip()
                s_user = User.objects.filter(
                    models.Q(username__iexact=s_ident) |
                    models.Q(id=int(s_ident) if s_ident.isdigit() else -1)
                ).first()
                if not s_user and ' ' in s_ident:
                    parts = s_ident.split(None, 1)
                    s_user = User.objects.filter(
                        first_name__iexact=parts[0],
                        last_name__iexact=parts[1]
                    ).first()
                if s_user:
                    credential_request.assigned_staff = s_user
                    credential_request.in_process_queue = True

        if in_process_queue is not None:
            credential_request.in_process_queue = bool(in_process_queue)

        # Allow Staff/Registrar/Admin to update remarks without changing status
        if canonical_status == current_status:
            if actor.role not in [Role.STAFF, Role.REGISTRAR, Role.ADMIN]:
                raise PermissionDenied(
                    "You do not have permission to update request remarks."
                )
            if remarks is not None:
                previous_remarks = credential_request.remarks
                credential_request.remarks = remarks
                credential_request.save()
                AuditService.log_action(
                    actor=actor,
                    action='REQUEST_REMARKS_UPDATED',
                    object_type='CredentialRequest',
                    object_id=credential_request.id,
                    previous_state={
                        'status': current_status,
                        'remarks': previous_remarks
                    },
                    new_state={'status': current_status, 'remarks': remarks}
                )
            else:
                credential_request.save()
            return credential_request

        allowed_transitions = CredentialRequestService.TRANSITION_MATRIX.get(
            current_status, [])

        transition = next(
            (t for t in allowed_transitions if t['status'] == canonical_status), None)

        if not transition:
            raise ValidationError(
                f"Invalid transition from {current_status} to {canonical_status}.")

        if actor.role not in transition['roles']:
            raise PermissionDenied(
                "You do not have permission to perform this transition."
            )

        if canonical_status in [
            RequestStatus.REJECTED,
            RequestStatus.REQUIREMENTS_REJECTED
        ] and not remarks:
            raise ValidationError("Remarks are required when rejecting a request.")

        previous_state = {
            'status': credential_request.status,
            'remarks': credential_request.remarks
        }

        credential_request.status = canonical_status
        if remarks is not None:
            credential_request.remarks = remarks

        if canonical_status in [
            RequestStatus.RELEASED,
            RequestStatus.REJECTED,
            RequestStatus.CANCELLED
        ]:
            credential_request.in_process_queue = False

        credential_request.save()

        new_state = {
            'status': credential_request.status,
            'remarks': credential_request.remarks
        }

        AuditService.log_action(
            actor=actor,
            action=f'REQUEST_STATUS_CHANGED_{canonical_status}',
            object_type='CredentialRequest',
            object_id=credential_request.id,
            previous_state=previous_state,
            new_state=new_state
        )

        if actor.role != Role.STUDENT:
            msg = (
                f"Your request ({credential_request.tracking_number}) "
                f"status changed to {canonical_status}."
            )
            NotificationService.create_notification(
                recipient=credential_request.user,
                event_type=NotificationEvent.REQUEST_STATUS_CHANGED,
                message=msg,
                related_object_type='CredentialRequest',
                related_object_id=str(credential_request.id)
            )

        return credential_request

    @staticmethod
    @transaction.atomic
    def restore_request(actor, credential_request, remarks=""):
        credential_request = (
            CredentialRequest.objects
            .select_for_update()
            .get(pk=credential_request.pk)
        )

        if actor.role != Role.ADMIN:
            raise PermissionDenied(
                "Only administrators can reopen or restore requests."
            )

        # Preserve verified clearance and payment steps without wiping records
        has_verified_payment = Payment.objects.filter(
            request=credential_request,
            status=PaymentStatus.VERIFIED
        ).exists()

        has_verified_clearance = StudentClearance.objects.filter(
            user=credential_request.user,
            status=ClearanceStatus.APPROVED
        ).exists()

        if has_verified_payment:
            target_status = RequestStatus.READY_FOR_RELEASE
        elif has_verified_clearance:
            target_status = RequestStatus.PAYMENT_PENDING
        else:
            target_status = RequestStatus.PENDING

        previous_state = {
            'status': credential_request.status,
            'remarks': credential_request.remarks,
        }

        credential_request.status = target_status
        credential_request.in_process_queue = True
        if remarks:
            credential_request.remarks = remarks
        else:
            credential_request.remarks = (
                f"Request restored to {target_status} by Admin {actor.username}."
            )
        credential_request.save()

        AuditService.log_action(
            actor=actor,
            action=f'REQUEST_RESTORED_{target_status}',
            object_type='CredentialRequest',
            object_id=credential_request.id,
            previous_state=previous_state,
            new_state={
                'status': credential_request.status,
                'remarks': credential_request.remarks,
                'in_process_queue': credential_request.in_process_queue,
            }
        )

        NotificationService.create_notification(
            recipient=credential_request.user,
            event_type=NotificationEvent.REQUEST_STATUS_CHANGED,
            message=(
                f"Your request ({credential_request.tracking_number}) "
                f"status changed to {target_status}."
            ),
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
        norm_status = str(status).strip().upper() if status else ''
        if norm_status in ['VERIFIED', 'APPROVED', ClearanceStatus.APPROVED]:
            canonical_status = ClearanceStatus.APPROVED
        elif norm_status in ['REJECTED', 'NOT_VERIFIED', ClearanceStatus.REJECTED]:
            canonical_status = ClearanceStatus.REJECTED
        elif norm_status in ['PENDING', 'RESET', ClearanceStatus.PENDING]:
            canonical_status = ClearanceStatus.PENDING
        else:
            raise ValidationError("Invalid clearance status.")

        # Idempotent review: If status is already canonical_status, succeed
        if clearance.status == canonical_status:
            clearance.reviewed_by = actor
            clearance.reviewed_at = timezone.now()
            if remarks:
                clearance.remarks = remarks
            clearance.save()
            return clearance

        if clearance.status != ClearanceStatus.PENDING:
            raise ValidationError("Only PENDING clearances can be reviewed.")

        if canonical_status == ClearanceStatus.REJECTED and not remarks:
            raise ValidationError("Remarks are required when rejecting a clearance.")

        previous_state = {
            'status': clearance.status,
            'remarks': clearance.remarks
        }

        clearance.status = canonical_status
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
            'CLEARANCE_APPROVED' if canonical_status == ClearanceStatus.APPROVED
            else 'CLEARANCE_REJECTED' if canonical_status == ClearanceStatus.REJECTED
            else 'CLEARANCE_RESET'
        )

        AuditService.log_action(
            actor=actor,
            action=audit_action,
            object_type='StudentClearance',
            object_id=clearance.id,
            previous_state=previous_state,
            new_state=new_state
        )

        if canonical_status in [ClearanceStatus.APPROVED, ClearanceStatus.REJECTED]:
            notification_event = (
                NotificationEvent.CLEARANCE_APPROVED
                if canonical_status == ClearanceStatus.APPROVED
                else NotificationEvent.CLEARANCE_REJECTED
            )
            msg = f"Your student clearance has been {canonical_status.lower()}."

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
        request = CredentialRequest.objects.select_for_update().get(pk=request.pk)

        if request.status != RequestStatus.PAYMENT_PENDING:
            raise ValidationError(
                "You can only submit an OTC payment when the request is "
                "awaiting payment."
            )

        if Payment.objects.filter(
            request=request, status=PaymentStatus.PENDING
        ).exists():
            raise ValidationError(
                "A payment submission is already pending review for this request."
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
            # This call is nested within verify_payment's atomic block.
            # Django creates a savepoint here; the select_for_update in
            # transition_request operates within the same connection and lock scope.
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
