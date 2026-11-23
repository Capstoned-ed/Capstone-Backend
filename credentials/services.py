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
    PaymentStatus,
    RegistrarSettings
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
                'roles': [Role.STAFF]},
            {'status': RequestStatus.PAYMENT_PENDING,
                'roles': [Role.STAFF]},
            {'status': RequestStatus.REJECTED,
                'roles': [Role.STAFF, Role.REGISTRAR]},
            {'status': RequestStatus.CANCELLED, 'roles': [Role.STUDENT]}
        ],
        RequestStatus.REQUIREMENTS_VERIFICATION: [
            {'status': RequestStatus.PENDING,
                'roles': [Role.STAFF]},
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
            {'status': RequestStatus.FOR_VERIFICATION,
                'roles': [Role.STUDENT, Role.STAFF, Role.REGISTRAR]},
            {'status': RequestStatus.PAYMENT_VERIFIED,
                'roles': [Role.STAFF, Role.REGISTRAR]},
            {'status': RequestStatus.CANCELLED, 'roles': [Role.STUDENT]},
            {'status': RequestStatus.REJECTED,
                'roles': [Role.STAFF, Role.REGISTRAR]}
        ],
        RequestStatus.FOR_VERIFICATION: [
            {'status': RequestStatus.PAYMENT_VERIFIED,
                'roles': [Role.STAFF, Role.REGISTRAR]},
            {'status': RequestStatus.PROCESSING,
                'roles': [Role.STAFF, Role.REGISTRAR]},
            {'status': RequestStatus.PAYMENT_PENDING,
                'roles': [Role.STAFF, Role.REGISTRAR]},
            {'status': RequestStatus.REJECTED,
                'roles': [Role.STAFF, Role.REGISTRAR]},
            {'status': RequestStatus.CANCELLED,
                'roles': [Role.STUDENT]}
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

        date_grad = str(validated_data.pop('date_of_graduation', None) or '').strip()
        if actor and getattr(actor, 'role', None) == Role.STUDENT:
            import re
            year_str = str(
                getattr(actor, 'year_level', '') or ''
            ).strip().lower()
            is_alumnus = 'alumn' in year_str or 'grad' in year_str
            if not is_alumnus:
                raw_remarks = str(validated_data.get('remarks') or '').lower()
                grad_patterns = [
                    r'\bfor board exam\b',
                    r'\bboard exam\b',
                    r'\bfor advanced studies\b',
                    r'\badvanced studies\b',
                    r'\bfor ranking\b',
                    r'\branking\b',
                ]
                if any(re.search(pat, raw_remarks) for pat in grad_patterns):
                    raise ValidationError(
                        "Purposes 'For Board Exam', 'For Advanced Studies', "
                        "and 'For Ranking' are reserved for alumni and graduates "
                        "only."
                    )
            elif date_grad:
                cur_remarks = str(validated_data.get('remarks') or '').strip()
                if not re.search(
                    r'\[(?:Date of Graduation|Graduation Date|Graduation):',
                    cur_remarks,
                    re.IGNORECASE,
                ):
                    validated_data['remarks'] = (
                        f"{cur_remarks} [Graduation: {date_grad}]".strip()
                    )

        copies = validated_data.pop('copies', None)
        if copies is not None:
            try:
                c_num = int(copies)
                if c_num < 1 or c_num > 100:
                    raise ValidationError(
                        "Number of copies must be between 1 and 100."
                    )
            except (ValueError, TypeError):
                raise ValidationError(
                    "Number of copies must be between 1 and 100."
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

        NotificationService.send_request_notification(
            user=actor,
            title=f"Request Submitted ({credential_request.tracking_number})",
            message=(
                f"Your credential request ({credential_request.tracking_number}) "
                f"for {credential_request.credential_type.name} has been submitted "
                "successfully. Status: Pending."
            ),
            reference_id=str(credential_request.id),
            send_email=True,
            event_type=NotificationEvent.REQUEST_CREATED,
            related_object_type='CredentialRequest',
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
    def transition_request(
        actor, credential_request, new_status, remarks="",
        assigned_staff=None, in_process_queue=None, release_date=None
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
            'FOR_VERIFICATION': RequestStatus.FOR_VERIFICATION,
            'FOR VERIFICATION': RequestStatus.FOR_VERIFICATION,
            'FOR_VERIFY': RequestStatus.FOR_VERIFICATION,
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
                    new_assigned_user = s_user

            if new_assigned_user:
                if (
                    new_assigned_user.role != Role.STAFF or
                    not new_assigned_user.is_active
                ):
                    raise ValidationError(
                        "Only active staff members can be assigned to requests."
                    )
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
            elif str(assigned_staff).strip().lower() in ['none', 'unassigned', '']:
                credential_request.assigned_staff = None
                credential_request.in_process_queue = False
                import re
                if credential_request.remarks:
                    credential_request.remarks = re.sub(
                        r'\[Assigned(?:\s+to)?:\s*[^\]]+\]', '',
                        credential_request.remarks
                    ).strip(' |')

        if in_process_queue is not None:
            credential_request.in_process_queue = bool(in_process_queue)

        def _preserve_metadata_tags(existing_text, new_text):
            import re
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

        if release_date:
            from datetime import datetime, date
            if isinstance(release_date, (datetime, date)):
                credential_request.release_date = (
                    release_date if isinstance(release_date, date)
                    else release_date.date()
                )
            elif isinstance(release_date, str) and release_date.strip():
                clean_str = release_date.strip().split('T')[0]
                try:
                    credential_request.release_date = datetime.strptime(
                        clean_str, '%Y-%m-%d'
                    ).date()
                except ValueError:
                    pass

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
            (t for t in allowed_transitions if t['status'] == canonical_status), None)

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
                f"Invalid transition from {current_status} to {canonical_status}.")

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
            if canonical_status == RequestStatus.PROCESSING:
                title = f"Request Processing ({credential_request.tracking_number})"
                msg = (
                    f"Your credential request ({credential_request.tracking_number}) "
                    "is now being processed."
                )
                NotificationService.send_request_notification(
                    user=credential_request.user,
                    title=title,
                    message=msg,
                    reference_id=str(credential_request.id),
                    send_email=True,
                    event_type=NotificationEvent.REQUEST_STATUS_CHANGED,
                )
            elif canonical_status == RequestStatus.READY_FOR_RELEASE:
                title = f"Ready for Release ({credential_request.tracking_number})"
                msg = (
                    f"Your requested credential ({credential_request.tracking_number}) "
                    "is ready for release. Please visit the Registrar's Office to "
                    "claim your document."
                )
                NotificationService.send_request_notification(
                    user=credential_request.user,
                    title=title,
                    message=msg,
                    reference_id=str(credential_request.id),
                    send_email=True,
                    event_type=NotificationEvent.REQUEST_STATUS_CHANGED,
                )
            elif canonical_status in [
                RequestStatus.REJECTED,
                RequestStatus.REQUIREMENTS_REJECTED
            ]:
                title = (
                    f"Request Action Required ({credential_request.tracking_number})"
                )
                clean_rem = str(credential_request.remarks or '').strip()
                msg = (
                    f"Your request ({credential_request.tracking_number}) requires "
                    f"action: {clean_rem or 'Please check your dashboard for details.'}"
                )
                NotificationService.send_request_notification(
                    user=credential_request.user,
                    title=title,
                    message=msg,
                    reference_id=str(credential_request.id),
                    send_email=True,
                    event_type=NotificationEvent.REQUEST_STATUS_CHANGED,
                )
            else:
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
                        message=f"Student clearance uploaded by {actor.username}.",
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

        if request.status not in [
            RequestStatus.PAYMENT_PENDING,
            RequestStatus.FOR_VERIFICATION
        ]:
            raise ValidationError(
                "You can only submit an OTC payment when the request is "
                "awaiting payment."
            )

        pending_payment = Payment.objects.filter(
            request=request, status=PaymentStatus.PENDING
        ).order_by('-uploaded_at').first()

        if receipt_reference_number and str(receipt_reference_number).strip():
            ref_clean = str(receipt_reference_number).strip()
            dup_qs = Payment.objects.filter(
                receipt_reference_number__iexact=ref_clean
            ).exclude(status=PaymentStatus.REJECTED)
            if pending_payment:
                dup_qs = dup_qs.exclude(pk=pending_payment.pk)
            if dup_qs.exists():
                err_msg = "This Official Receipt (O.R.) number is already in use."
                raise ValidationError({
                    'or_number': [err_msg],
                    'receipt_reference_number': [err_msg]
                })

        ref_str = (
            str(receipt_reference_number).strip()
            if receipt_reference_number
            else ""
        )

        if pending_payment:
            pending_payment.amount = amount
            pending_payment.receipt_reference_number = ref_str
            if receipt_image:
                pending_payment.receipt_image = receipt_image
            pending_payment.uploaded_at = timezone.now()
            pending_payment.save()
            payment = pending_payment
        else:
            payment = Payment.objects.create(
                request=request,
                amount=amount,
                receipt_reference_number=ref_str,
                receipt_image=receipt_image,
                status=PaymentStatus.PENDING
            )

        # Transition request status from PAYMENT_PENDING to FOR_VERIFICATION
        if request.status == RequestStatus.PAYMENT_PENDING:
            request.status = RequestStatus.FOR_VERIFICATION
            request.save(update_fields=['status', 'updated_at'])
            AuditService.log_action(
                actor=actor,
                action='REQUEST_STATUS_CHANGED_FOR_VERIFICATION',
                object_type='CredentialRequest',
                object_id=request.id,
                previous_state={'status': RequestStatus.PAYMENT_PENDING},
                new_state={'status': RequestStatus.FOR_VERIFICATION}
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
                    f"Payment receipt uploaded for request {request.tracking_number} "
                    f"by {actor.username}."
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
            NotificationService.send_request_notification(
                user=payment.request.user,
                title=f"Payment Verified ({payment.request.tracking_number})",
                message=(
                    f"Your payment for request {payment.request.tracking_number} "
                    "has been verified and is now processing."
                ),
                reference_id=str(payment.request.id),
                send_email=True,
                event_type=NotificationEvent.PAYMENT_VERIFIED,
                related_object_type='Payment',
            )
        else:
            if payment.request.status == RequestStatus.FOR_VERIFICATION:
                CredentialRequestService.transition_request(
                    actor=actor,
                    credential_request=payment.request,
                    new_status=RequestStatus.PAYMENT_PENDING,
                    remarks=f"Payment rejected: {remarks}"
                )
            NotificationService.send_request_notification(
                user=payment.request.user,
                title=f"Payment Rejected ({payment.request.tracking_number})",
                message=(
                    f"Your OTC payment for request "
                    f"{payment.request.tracking_number} was rejected: "
                    f"{remarks or 'Please re-upload a valid proof of payment.'}"
                ),
                reference_id=str(payment.request.id),
                send_email=True,
                event_type=NotificationEvent.PAYMENT_REJECTED,
                related_object_type='Payment',
            )

        return payment
