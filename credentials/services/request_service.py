import re
from django.contrib.auth import get_user_model
from django.db import models, transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from accounts.models import Role
from audit.services import AuditService
from notifications.models import NotificationEvent
from notifications.services import NotificationService
from ..models import (
    ClearanceStatus,
    CredentialRequest,
    Payment,
    PaymentStatus,
    RegistrarSettings,
    RequestStatus,
    StudentClearance,
)

User = get_user_model()


class CredentialRequestService:
    TRANSITION_MATRIX = {
        RequestStatus.PENDING: [
            {'status': RequestStatus.REQUIREMENTS_VERIFICATION,
                'roles': [Role.STAFF]},
            {'status': RequestStatus.PAYMENT_PENDING,
                'roles': [Role.STAFF]},
            {'status': RequestStatus.REJECTED,
                'roles': [Role.STAFF, Role.REGISTRAR]},
            {'status': RequestStatus.CANCELLED, 'roles': [Role.STUDENT]}
        ],
        RequestStatus.REQUIREMENTS_VERIFICATION: [
            {'status': RequestStatus.PAYMENT_PENDING,
                'roles': [Role.STAFF]},
            {'status': RequestStatus.REQUIREMENTS_REJECTED,
                'roles': [Role.STAFF]},
            {'status': RequestStatus.REJECTED,
                'roles': [Role.STAFF, Role.REGISTRAR]}
        ],
        RequestStatus.REQUIREMENTS_REJECTED: [
            {'status': RequestStatus.PENDING, 'roles': [Role.STUDENT]},
            {'status': RequestStatus.CANCELLED, 'roles': [Role.STUDENT]}
        ],
        RequestStatus.PAYMENT_PENDING: [
            {'status': RequestStatus.PAYMENT_VERIFIED,
                'roles': [Role.STAFF, Role.REGISTRAR]},
            {'status': RequestStatus.CANCELLED, 'roles': [Role.STUDENT]},
            {'status': RequestStatus.REJECTED,
                'roles': [Role.STAFF, Role.REGISTRAR]}
        ],
        RequestStatus.PAYMENT_VERIFIED: [
            {'status': RequestStatus.PROCESSING, 'roles': [
                Role.REGISTRAR, Role.STAFF
            ]},
            {'status': RequestStatus.READY_FOR_RELEASE, 'roles': [
                Role.REGISTRAR, Role.STAFF
            ]},
            {'status': RequestStatus.REJECTED, 'roles': [
                Role.REGISTRAR
            ]}
        ],
        RequestStatus.PROCESSING: [
            {'status': RequestStatus.READY_FOR_RELEASE, 'roles': [
                Role.REGISTRAR
            ]},
            {'status': RequestStatus.REJECTED, 'roles': [
                Role.REGISTRAR
            ]}
        ],
        RequestStatus.READY_FOR_RELEASE: [
            {'status': RequestStatus.RELEASED, 'roles': [
                Role.REGISTRAR, Role.STAFF
            ]},
            {'status': RequestStatus.REJECTED, 'roles': [
                Role.REGISTRAR
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
            .filter(user=actor, credential_request__isnull=True)
            .order_by('-uploaded_at')
            .first()
        )
        if not clearance:
            clearance = (
                StudentClearance.objects
                .select_for_update()
                .filter(user=actor)
                .order_by('-uploaded_at')
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

        # Bind clearance strictly to this request in PENDING state for staff review
        if clearance.credential_request is None:
            clearance.credential_request = credential_request
            clearance.save(update_fields=['credential_request'])
        else:
            # Reusing file for new request: create fresh PENDING record
            clearance = StudentClearance.objects.create(
                user=actor,
                credential_request=credential_request,
                file=clearance.file,
                status=ClearanceStatus.PENDING
            )

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

        # Notify operational Registrar (Admin is not a request processor)
        registrar_users = User.objects.filter(
            role=Role.REGISTRAR,
            is_active=True
        )
        for reg_user in registrar_users:
            if reg_user != actor:
                NotificationService.create_notification(
                    recipient=reg_user,
                    event_type=NotificationEvent.REQUEST_CREATED,
                    message=(
                        f"New credential request "
                        f"({credential_request.tracking_number}) "
                        f"submitted by {actor.username} for "
                        f"{credential_request.credential_type.name}."
                    ),
                    related_object_type='CredentialRequest',
                    related_object_id=str(credential_request.id)
                )

        if (
            credential_request.assigned_staff and
            credential_request.assigned_staff not in registrar_users and
            credential_request.assigned_staff != actor
        ):
            NotificationService.create_notification(
                recipient=credential_request.assigned_staff,
                event_type=NotificationEvent.REQUEST_CREATED,
                message=(
                    f"New credential request ({credential_request.tracking_number}) "
                    f"assigned to you by {actor.username}."
                ),
                related_object_type='CredentialRequest',
                related_object_id=str(credential_request.id)
            )

        return credential_request

    @staticmethod
    @transaction.atomic
    def assign_request(actor, credential_request, target_staff_identifier):
        if actor.role not in [Role.STAFF, Role.REGISTRAR, Role.ADMIN]:
            raise PermissionDenied(
                "You do not have permission to assign requests."
            )

        credential_request = (
            CredentialRequest.objects
            .select_for_update()
            .get(pk=credential_request.pk)
        )

        staff_user = None
        if target_staff_identifier:
            raw_target = str(target_staff_identifier).strip()
            staff_user = User.objects.filter(
                models.Q(username__iexact=raw_target) |
                models.Q(
                    id=int(raw_target) if raw_target.isdigit() else -1
                )
            ).first()
            if not staff_user and ' ' in raw_target:
                parts = raw_target.split(None, 1)
                staff_user = User.objects.filter(
                    first_name__iexact=parts[0],
                    last_name__iexact=parts[1]
                ).first()
            if not staff_user:
                staff_user = User.objects.filter(
                    models.Q(first_name__iexact=raw_target) |
                    models.Q(last_name__iexact=raw_target) |
                    models.Q(email__iexact=raw_target)
                ).first()
        if not staff_user:
            staff_user = actor

        credential_request.assigned_staff = staff_user
        credential_request.in_process_queue = True

        staff_display = staff_user.username or 'Staff'
        clean_rem = re.sub(
            r'\[Assigned(?:\s+to)?:\s*[^\]]+\]', '',
            credential_request.remarks or ''
        ).strip()
        new_rem = f"{clean_rem} | [Assigned to: {staff_display}]".strip(' |')
        credential_request.remarks = new_rem
        credential_request.save()

        AuditService.log_action(
            actor=actor,
            action='REQUEST_ASSIGNED',
            object_type='CredentialRequest',
            object_id=credential_request.id,
            previous_state=None,
            new_state={
                'assigned_staff': staff_user.username,
                'in_process_queue': True,
                'remarks': credential_request.remarks
            }
        )

        if staff_user != actor:
            NotificationService.create_notification(
                recipient=staff_user,
                event_type=NotificationEvent.REQUEST_ASSIGNED,
                message=(
                    f"Request {credential_request.tracking_number} has been assigned "
                    f"to you by {actor.username}."
                ),
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
            'APPROVED': RequestStatus.READY_FOR_RELEASE,
            'APPROVED / READY FOR RELEASE': RequestStatus.READY_FOR_RELEASE,
            'PENDING_REGISTRAR_APPROVAL': 'PENDING_REGISTRAR_APPROVAL',
            'PENDING REGISTRAR APPROVAL': 'PENDING_REGISTRAR_APPROVAL',
            'RETURNED TO STAFF / FOR PROCESSING': RequestStatus.PAYMENT_VERIFIED,
            'RELEASED / COMPLETED': RequestStatus.RELEASED,
            'CLAIMED': RequestStatus.RELEASED,
            'COMPLETED': RequestStatus.RELEASED,
        }
        clean_key = str(new_status).strip().upper().replace('-', '_')
        canonical_status = status_map.get(clean_key, clean_key)

        settings_obj = RegistrarSettings.get_settings()
        auto_approved_bypass = False

        # When Staff sends a request to PENDING_REGISTRAR_APPROVAL, check
        # persisted Registrar Auto-Approve setting: if True, bypass straight to
        # READY_FOR_RELEASE; if False, pause in PROCESSING for manual approval.
        if canonical_status == 'PENDING_REGISTRAR_APPROVAL':
            if settings_obj.auto_approve_requests:
                canonical_status = RequestStatus.READY_FOR_RELEASE
                auto_approved_bypass = True
            else:
                canonical_status = RequestStatus.PROCESSING

        if clean_key in ['RESTORE', 'REOPEN']:
            return CredentialRequestService.restore_request(
                actor=actor,
                credential_request=credential_request,
                remarks=remarks
            )

        # Handle staff assignment if provided
        if assigned_staff is not None:
            new_assigned_user = None
            if isinstance(assigned_staff, User):
                new_assigned_user = assigned_staff
            elif (
                isinstance(assigned_staff, (str, int)) and
                str(assigned_staff).strip()
            ):
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
                    new_assigned_user = s_user

            if new_assigned_user:
                prev_staff = credential_request.assigned_staff
                credential_request.assigned_staff = new_assigned_user
                credential_request.in_process_queue = True
                if new_assigned_user != prev_staff and new_assigned_user != actor:
                    NotificationService.create_notification(
                        recipient=new_assigned_user,
                        event_type=NotificationEvent.REQUEST_ASSIGNED,
                        message=(
                            f"Request {credential_request.tracking_number} has been "
                            f"assigned to you by {actor.username}."
                        ),
                        related_object_type='CredentialRequest',
                        related_object_id=str(credential_request.id)
                    )

        if in_process_queue is not None:
            credential_request.in_process_queue = bool(in_process_queue)

        def _preserve_metadata_tags(existing_text, new_text):
            existing = str(existing_text or '')
            updated = str(new_text or '').strip()
            tags_to_keep = []
            patterns = [
                (r'\[Copies:[^\]]+\]', r'\[Copies:'),
                (r'\[Total:[^\]]+\]', r'\[Total:'),
                (r'\[Items:\[[\s\S]*?\]\]', r'\[Items:\['),
            ]
            for full_pat, check_pat in patterns:
                if not re.search(check_pat, updated, re.IGNORECASE):
                    m = re.search(full_pat, existing, re.IGNORECASE)
                    if m:
                        tags_to_keep.append(m.group(0))
            if tags_to_keep:
                return ' '.join(
                    p for p in [updated, *tags_to_keep] if p
                ).strip()
            return updated

        # Allow Staff/Registrar/Admin to update remarks without changing status
        if canonical_status == current_status:
            if actor.role not in [Role.STAFF, Role.REGISTRAR, Role.ADMIN]:
                raise PermissionDenied(
                    "You do not have permission to update request remarks."
                )
            if remarks is not None:
                previous_remarks = credential_request.remarks
                credential_request.remarks = _preserve_metadata_tags(
                    previous_remarks, remarks
                )
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
                    new_state={
                        'status': current_status,
                        'remarks': credential_request.remarks
                    }
                )
            else:
                credential_request.save()
            return credential_request

        allowed_transitions = CredentialRequestService.TRANSITION_MATRIX.get(
            current_status, [])

        transition = next(
            (t for t in allowed_transitions if t['status'] == canonical_status),
            None
        )

        # Allow Registrar to return a request from PROCESSING / READY_FOR_RELEASE
        # back to Staff (PAYMENT_VERIFIED) without altering Staff's matrix.
        if (
            not transition
            and actor.role == Role.REGISTRAR
            and current_status in [
                RequestStatus.PROCESSING, RequestStatus.READY_FOR_RELEASE
            ]
            and canonical_status == RequestStatus.PAYMENT_VERIFIED
        ):
            transition = {
                'status': RequestStatus.PAYMENT_VERIFIED,
                'roles': [Role.REGISTRAR],
            }

        if not transition:
            raise ValidationError(
                f"Invalid transition from {current_status} to {canonical_status}."
            )

        # Admins have strictly read-only access to request status processing
        if actor.role == Role.ADMIN:
            raise PermissionDenied(
                "Admins have read-only access to request processing."
            )

        # When Auto-Approve is ON and Staff hands a PROCESSING request off via
        # PENDING_REGISTRAR_APPROVAL, bypass manual Registrar approval straight
        # to READY_FOR_RELEASE; raw direct READY_FOR_RELEASE stays Registrar-only.
        if (
            auto_approved_bypass
            and actor.role == Role.STAFF
            and canonical_status == RequestStatus.READY_FOR_RELEASE
            and settings_obj.auto_approve_requests
        ):
            pass
        elif actor.role not in transition['roles']:
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
            credential_request.remarks = _preserve_metadata_tags(
                previous_state['remarks'], remarks
            )

        # Persist Staff processor in DB if request was unassigned
        if (
            credential_request.assigned_staff is None
            and actor.role == Role.STAFF
        ):
            credential_request.assigned_staff = actor
            credential_request.in_process_queue = True

        if canonical_status in [
            RequestStatus.RELEASED,
            RequestStatus.REJECTED,
            RequestStatus.CANCELLED
        ]:
            credential_request.in_process_queue = False

        # Registrar Auto-Approval & Signatory Gate
        auto_approve_audit_note = None
        if settings_obj.auto_approve_requests:
            if (
                not credential_request.is_approved
                or auto_approved_bypass
            ) and canonical_status in [
                RequestStatus.REQUIREMENTS_VERIFICATION,
                RequestStatus.PAYMENT_PENDING,
                RequestStatus.PAYMENT_VERIFIED,
                RequestStatus.PROCESSING,
                RequestStatus.READY_FOR_RELEASE,
                RequestStatus.RELEASED
            ]:
                signatory_name, reg_user = RegistrarSettings.get_active_signatory()
                credential_request.is_approved = True
                credential_request.is_auto_approved = True
                credential_request.approved_by = reg_user or (
                    actor if actor.role == Role.REGISTRAR else None
                )
                credential_request.approved_by_name = signatory_name
                credential_request.approved_at = timezone.now()
                if auto_approved_bypass:
                    auto_approve_audit_note = (
                        "Auto-approved via Registrar Auto-Approve setting"
                    )
                    if auto_approve_audit_note not in (
                        credential_request.remarks or ''
                    ):
                        combined = (
                            f"{credential_request.remarks or ''} "
                            f"{auto_approve_audit_note}"
                        ).strip()
                        credential_request.remarks = _preserve_metadata_tags(
                            previous_state['remarks'], combined
                        )
        else:
            if not credential_request.is_approved:
                if canonical_status in [
                    RequestStatus.READY_FOR_RELEASE,
                    RequestStatus.RELEASED
                ]:
                    raise ValidationError(
                        "This request requires Registrar approval before it can "
                        "proceed to release."
                    )

        credential_request.save()

        new_state = {
            'status': credential_request.status,
            'remarks': credential_request.remarks
        }
        if auto_approve_audit_note:
            new_state['auto_approved_note'] = auto_approve_audit_note

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

    @staticmethod
    @transaction.atomic
    def approve_request(actor, credential_request):
        credential_request = (
            CredentialRequest.objects
            .select_for_update()
            .get(pk=credential_request.pk)
        )
        if actor.role not in [Role.REGISTRAR, Role.ADMIN]:
            raise PermissionDenied(
                "Only Registrar or Admin can approve credential requests."
            )

        first = getattr(actor, 'first_name', '')
        last = getattr(actor, 'last_name', '')
        name = f"{first} {last}".strip() or actor.username

        credential_request.is_approved = True
        credential_request.is_auto_approved = False
        credential_request.approved_by = actor
        credential_request.approved_by_name = name
        credential_request.approved_at = timezone.now()
        credential_request.save(update_fields=[
            'is_approved', 'is_auto_approved', 'approved_by',
            'approved_by_name', 'approved_at', 'updated_at'
        ])

        AuditService.log_action(
            actor=actor,
            action='REQUEST_APPROVED_BY_REGISTRAR',
            object_type='CredentialRequest',
            object_id=credential_request.id,
            previous_state={'is_approved': False},
            new_state={
                'is_approved': True,
                'approved_by': str(actor.id),
                'approved_by_name': name
            }
        )

        if (
            credential_request.assigned_staff and
            credential_request.assigned_staff != actor
        ):
            NotificationService.create_notification(
                recipient=credential_request.assigned_staff,
                event_type=NotificationEvent.REQUEST_STATUS_CHANGED,
                message=(
                    f"Request {credential_request.tracking_number} has been "
                    f"approved by Registrar {name}."
                ),
                related_object_type='CredentialRequest',
                related_object_id=str(credential_request.id)
            )

        return credential_request

