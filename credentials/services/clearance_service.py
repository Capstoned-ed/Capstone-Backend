from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from accounts.models import Role
from audit.services import AuditService
from notifications.models import NotificationEvent
from notifications.services import NotificationService
from ..models import (
    ClearanceStatus,
    CredentialRequest,
    RequestStatus,
    StudentClearance,
)

User = get_user_model()


class StudentClearanceService:
    @staticmethod
    @transaction.atomic
    def submit_clearance(actor, file, credential_request=None):
        if credential_request:
            clearance = StudentClearance.objects.filter(
                user=actor, credential_request=credential_request
            ).first()
        else:
            clearance = StudentClearance.objects.filter(
                user=actor, credential_request__isnull=True
            ).first()

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
                user=actor,
                credential_request=credential_request,
                file=file,
                status=ClearanceStatus.PENDING
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

        active_requests = CredentialRequest.objects.filter(
            user=actor
        ).exclude(
            status__in=[
                RequestStatus.RELEASED,
                RequestStatus.REJECTED,
                RequestStatus.CANCELLED
            ]
        )
        notified_staff = set()
        for req in active_requests:
            if (
                req.assigned_staff and
                req.assigned_staff not in notified_staff and
                req.assigned_staff != actor
            ):
                NotificationService.create_notification(
                    recipient=req.assigned_staff,
                    event_type=NotificationEvent.CLEARANCE_SUBMITTED,
                    message=(
                        f"Student clearance uploaded by {actor.username} "
                        f"for request {req.tracking_number}."
                    ),
                    related_object_type='StudentClearance',
                    related_object_id=str(clearance.id)
                )
                notified_staff.add(req.assigned_staff)

        if not notified_staff:
            registrars = User.objects.filter(
                role=Role.REGISTRAR, is_active=True
            )
            for reg_user in registrars:
                if reg_user != actor:
                    NotificationService.create_notification(
                        recipient=reg_user,
                        event_type=NotificationEvent.CLEARANCE_SUBMITTED,
                        message=(
                            f"Student clearance uploaded by {actor.username}."
                        ),
                        related_object_type='StudentClearance',
                        related_object_id=str(clearance.id)
                    )

        return clearance

    @staticmethod
    @transaction.atomic
    def review_clearance(actor, clearance, status, remarks=""):
        norm_status = str(status).strip().upper() if status else ''
        if norm_status in ['VERIFIED', 'APPROVED', ClearanceStatus.APPROVED]:
            canonical_status = ClearanceStatus.APPROVED
        elif norm_status in [
            'REJECTED', 'NOT_VERIFIED', ClearanceStatus.REJECTED
        ]:
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
            raise ValidationError(
                "Remarks are required when rejecting a clearance."
            )

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
            'CLEARANCE_APPROVED'
            if canonical_status == ClearanceStatus.APPROVED
            else 'CLEARANCE_REJECTED'
            if canonical_status == ClearanceStatus.REJECTED
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

        if canonical_status in [
            ClearanceStatus.APPROVED, ClearanceStatus.REJECTED
        ]:
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

