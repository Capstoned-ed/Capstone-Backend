from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from accounts.models import Role
from audit.services import AuditService
from notifications.models import NotificationEvent
from notifications.services import NotificationService
from .request_service import CredentialRequestService
from ..models import (
    CredentialRequest,
    Payment,
    PaymentStatus,
    RequestStatus,
)

User = get_user_model()


class PaymentService:
    @staticmethod
    @transaction.atomic
    def submit_payment(
        actor, request, amount, receipt_image, receipt_reference_number=""
    ):
        request = (
            CredentialRequest.objects
            .select_for_update()
            .get(pk=request.pk)
        )

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

        if receipt_reference_number and str(receipt_reference_number).strip():
            ref_clean = str(receipt_reference_number).strip()
            if Payment.objects.filter(
                receipt_reference_number__iexact=ref_clean
            ).exclude(status=PaymentStatus.REJECTED).exists():
                raise ValidationError(
                    f"Receipt / O.R. reference number '{ref_clean}' has "
                    "already been used."
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

        target_staff = request.assigned_staff
        if target_staff and target_staff != actor:
            NotificationService.create_notification(
                recipient=target_staff,
                event_type=NotificationEvent.PAYMENT_SUBMITTED,
                message=(
                    f"Payment receipt uploaded for request "
                    f"{request.tracking_number} by {actor.username}."
                ),
                related_object_type='Payment',
                related_object_id=str(payment.id)
            )
        else:
            registrars = User.objects.filter(
                role=Role.REGISTRAR, is_active=True
            )
            for reg_user in registrars:
                if reg_user != actor:
                    NotificationService.create_notification(
                        recipient=reg_user,
                        event_type=NotificationEvent.PAYMENT_SUBMITTED,
                        message=(
                            f"Payment receipt uploaded for request "
                            f"{request.tracking_number} by {actor.username}."
                        ),
                        related_object_type='Payment',
                        related_object_id=str(payment.id)
                    )

        return payment

    @staticmethod
    @transaction.atomic
    def verify_payment(actor, payment, action, remarks=""):
        if action not in ['VERIFY', 'REJECT']:
            raise ValidationError("Action must be VERIFY or REJECT.")

        if action == 'REJECT' and not remarks:
            raise ValidationError(
                "Remarks are required when rejecting an OTC payment."
            )

        previous_state = {
            'status': payment.status,
            'remarks': payment.remarks,
            'verified_by': (
                payment.verified_by.id if payment.verified_by else None
            )
        }

        payment.status = (
            PaymentStatus.VERIFIED
            if action == 'VERIFY'
            else PaymentStatus.REJECTED
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

