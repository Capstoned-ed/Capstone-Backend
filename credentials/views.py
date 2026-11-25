from rest_framework import viewsets, status
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from pathlib import Path
from django.contrib.auth import get_user_model
from django.db import models
from django.http import FileResponse
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from audit.services import AuditService

from .models import (
    CredentialType,
    CredentialRequest,
    RequirementDocument,
    StudentClearance,
    Payment,
    RegistrarSettings,
    RequestStatus,
)
from .serializers import (
    CredentialTypeSerializer,
    CredentialTypeCreateUpdateSerializer,
    CredentialRequestSerializer,
    RequirementDocumentSerializer,
    StudentClearanceSerializer,
    StudentClearanceSubmitSerializer,
    StudentClearanceReviewSerializer,
    PaymentSerializer,
    RegistrarSettingsSerializer
)
from .permissions import (
    IsAdminOrRegistrarOrReadOnly,
    CredentialRequestPermission,
    RequirementDocumentPermission,
    StudentClearancePermission,
    PaymentPermission
)
from .services import (
    CredentialTypeService,
    CredentialRequestService,
    RequirementDocumentService,
    StudentClearanceService,
    PaymentService
)
from accounts.models import Role
from notifications.services import NotificationService
from notifications.models import NotificationEvent
from .ml_client import MLClient

User = get_user_model()


class CredentialTypeViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing credential types.
    """
    # Base queryset for router URL introspection; actual filtering in get_queryset().
    queryset = CredentialType.objects.all().order_by('name')
    permission_classes = [IsAdminOrRegistrarOrReadOnly]

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return CredentialTypeCreateUpdateSerializer
        return CredentialTypeSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user

        include_inactive = (
            self.request.query_params.get('include_inactive') == 'true' or
            self.request.query_params.get('all') == 'true'
        )
        is_admin_or_reg = (
            user.is_authenticated and
            user.role in [Role.ADMIN, Role.REGISTRAR]
        )
        if not include_inactive and not is_admin_or_reg:
            return qs.filter(is_active=True)

        return qs

    @extend_schema(responses={201: CredentialTypeSerializer})
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        credential_type = CredentialTypeService.create_type(
            actor=request.user,
            validated_data=serializer.validated_data
        )
        headers = self.get_success_headers(serializer.data)
        return Response(
            CredentialTypeSerializer(credential_type).data,
            status=status.HTTP_201_CREATED,
            headers=headers
        )

    @extend_schema(responses={200: CredentialTypeSerializer})
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        credential_type = CredentialTypeService.update_type(
            actor=request.user,
            credential_type=instance,
            validated_data=serializer.validated_data
        )

        if getattr(instance, '_prefetched_objects_cache', None):
            instance._prefetched_objects_cache = {}

        return Response(CredentialTypeSerializer(credential_type).data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        CredentialTypeService.deactivate_type(
            actor=request.user,
            credential_type=instance
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class CredentialRequestViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing credential requests.
    """
    serializer_class = CredentialRequestSerializer
    permission_classes = [CredentialRequestPermission]
    pagination_class = None

    def get_queryset(self):
        qs = CredentialRequest.objects.select_related(
            'user', 'credential_type', 'assigned_staff', 'approved_by'
        ).prefetch_related(
            'payments',
            'documents',
            'clearance_records'
        ).order_by('-created_at')

        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param)

        assigned_param = (
            self.request.query_params.get('assigned_to') or
            self.request.query_params.get('assigned_staff')
        )
        assigned_only = self.request.query_params.get('assigned_only')

        user = self.request.user

        if assigned_param:
            raw_target = str(assigned_param).strip()
            if raw_target.lower() == 'me' and user.is_authenticated:
                target_user = user
            else:
                target_user = User.objects.filter(
                    models.Q(username__iexact=raw_target) |
                    models.Q(
                        id=int(raw_target) if raw_target.isdigit() else -1
                    )
                ).first()
                if not target_user and ' ' in raw_target:
                    parts = raw_target.split(None, 1)
                    target_user = User.objects.filter(
                        first_name__iexact=parts[0],
                        last_name__iexact=parts[1]
                    ).first()
                if not target_user:
                    target_user = User.objects.filter(
                        models.Q(first_name__iexact=raw_target) |
                        models.Q(last_name__iexact=raw_target) |
                        models.Q(email__iexact=raw_target)
                    ).first()

            if target_user:
                assigned_q = (
                    models.Q(assigned_staff=target_user) |
                    models.Q(
                        remarks__icontains=f"Assigned to: {target_user.username}"
                    )
                )
                target_full_name = (
                    f"{getattr(target_user, 'first_name', '')} "
                    f"{getattr(target_user, 'last_name', '')}"
                ).strip()
                if target_full_name:
                    assigned_q |= models.Q(
                        remarks__icontains=f"Assigned to: {target_full_name}"
                    )
                qs = qs.filter(assigned_q)
            else:
                qs = qs.none()
        elif assigned_only == 'true' and user.is_authenticated:
            qs = qs.filter(
                models.Q(assigned_staff=user) |
                models.Q(remarks__icontains=f"Assigned to: {user.username}")
            )

        if user.is_authenticated and user.role == Role.STUDENT:
            return qs.filter(user=user)

        if user.is_authenticated and user.role == Role.STAFF:
            return qs.filter(
                status__in=[
                    RequestStatus.PAYMENT_VERIFIED,
                    RequestStatus.PROCESSING,
                    RequestStatus.READY_FOR_RELEASE,
                    RequestStatus.RELEASED,
                ]
            )

        return qs

    def get_object(self):
        queryset = self.filter_queryset(self.get_queryset())
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        lookup_value = str(self.kwargs[lookup_url_kwarg]).strip()

        # 1. Attempt lookup by UUID pk
        try:
            import uuid
            uuid_val = uuid.UUID(lookup_value)
            obj = queryset.filter(pk=uuid_val).first()
            if obj:
                self.check_object_permissions(self.request, obj)
                return obj
        except (ValueError, TypeError, AttributeError):
            pass

        # 2. Attempt lookup by tracking_number
        obj = queryset.filter(tracking_number__iexact=lookup_value).first()
        if obj:
            self.check_object_permissions(self.request, obj)
            return obj

        # If not found in filtered queryset, check if an unverified request exists
        # so Staff receives 403 Forbidden instead of generic 404.
        if self.request.user.is_authenticated and self.request.user.role == Role.STAFF:
            raw_obj = None
            try:
                import uuid
                u_val = uuid.UUID(lookup_value)
                raw_obj = CredentialRequest.objects.filter(pk=u_val).first()
            except (ValueError, TypeError, AttributeError):
                pass
            if not raw_obj:
                raw_obj = CredentialRequest.objects.filter(
                    tracking_number__iexact=lookup_value
                ).first()
            if raw_obj:
                from rest_framework.exceptions import (
                    PermissionDenied as DFPendingDenied
                )
                raise DFPendingDenied(
                    "Staff cannot access or process unverified requests."
                )

        return super().get_object()

    @extend_schema(responses={201: CredentialRequestSerializer})
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        credential_request = CredentialRequestService.create_request(
            actor=request.user,
            validated_data=serializer.validated_data
        )
        headers = self.get_success_headers(serializer.data)
        return Response(
            CredentialRequestSerializer(
                credential_request, context={'request': request}
            ).data,
            status=status.HTTP_201_CREATED,
            headers=headers
        )

    def update(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def partial_update(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def destroy(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    @extend_schema(responses={200: CredentialRequestSerializer})
    @action(detail=True, methods=['patch', 'post'])
    def assign(self, request, pk=None):
        credential_request = self.get_object()
        if request.user.role not in [Role.STAFF, Role.REGISTRAR, Role.ADMIN]:
            return Response(
                {"detail": "You do not have permission to assign requests."},
                status=status.HTTP_403_FORBIDDEN
            )

        has_assign_param = (
            'assigned_staff' in request.data or
            'assigned_to' in request.data
        )
        target_staff_identifier = (
            request.data.get('assigned_staff')
            if 'assigned_staff' in request.data
            else request.data.get('assigned_to')
        )
        if not has_assign_param:
            target_staff_identifier = request.user.username

        import re
        if (
            target_staff_identifier is None or
            str(target_staff_identifier).strip() == '' or
            str(target_staff_identifier).strip().lower() in ['unassigned', 'none']
        ):
            credential_request.assigned_staff = None
            credential_request.in_process_queue = False
            clean_rem = re.sub(
                r'\[Assigned(?:\s+to)?:\s*[^\]]+\]', '',
                credential_request.remarks or ''
            ).strip(' |')
            credential_request.remarks = clean_rem
            credential_request.save()

            from audit.services import AuditService
            AuditService.log_action(
                actor=request.user,
                action='REQUEST_UNASSIGNED',
                object_type='CredentialRequest',
                object_id=credential_request.id,
                previous_state=None,
                new_state={
                    'assigned_staff': None,
                    'in_process_queue': False,
                    'remarks': credential_request.remarks
                }
            )
            return Response(
                CredentialRequestSerializer(
                    credential_request, context={'request': request}
                ).data,
                status=status.HTTP_200_OK
            )

        raw_target = str(target_staff_identifier).strip()
        unverified_statuses = [
            RequestStatus.PENDING,
            RequestStatus.REQUIREMENTS_VERIFICATION,
            RequestStatus.REQUIREMENTS_REJECTED,
            RequestStatus.PAYMENT_PENDING,
            RequestStatus.FOR_VERIFICATION,
        ]
        if credential_request.status in unverified_statuses:
            return Response(
                {
                    "detail": (
                        "Cannot assign staff to an unverified request. "
                        "Please verify clearance and payment first."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

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

        if not staff_user or staff_user.role != Role.STAFF or not staff_user.is_active:
            return Response(
                {"detail": "Only active staff members can be assigned to requests."},
                status=status.HTTP_400_BAD_REQUEST
            )

        credential_request.assigned_staff = staff_user
        credential_request.in_process_queue = True

        import re
        staff_display = staff_user.username or 'Staff'
        clean_rem = re.sub(
            r'\[Assigned(?:\s+to)?:\s*[^\]]+\]', '',
            credential_request.remarks or ''
        ).strip()
        new_rem = f"{clean_rem} | [Assigned to: {staff_display}]".strip(' |')
        credential_request.remarks = new_rem
        credential_request.save()

        from audit.services import AuditService
        AuditService.log_action(
            actor=request.user,
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

        if staff_user != request.user:
            NotificationService.create_notification(
                recipient=staff_user,
                title=f"Request Assigned ({credential_request.tracking_number})",
                event_type=NotificationEvent.REQUEST_ASSIGNED,
                message=(
                    f"Request {credential_request.tracking_number} has been assigned "
                    f"to you by {request.user.username}."
                ),
                related_object_type='CredentialRequest',
                related_object_id=str(credential_request.id)
            )

        return Response(
            CredentialRequestSerializer(
                credential_request, context={'request': request}
            ).data,
            status=status.HTTP_200_OK
        )

    @extend_schema(responses={200: CredentialRequestSerializer})
    @action(detail=True, methods=['patch'])
    def transition(self, request, pk=None):
        credential_request = self.get_object()

        unverified_statuses = [
            RequestStatus.PENDING,
            RequestStatus.REQUIREMENTS_VERIFICATION,
            RequestStatus.REQUIREMENTS_REJECTED,
            RequestStatus.PAYMENT_PENDING,
            RequestStatus.FOR_VERIFICATION,
        ]
        new_status = request.data.get('status')
        canonical_target = (
            CredentialRequestService.get_canonical_status(new_status)
            if new_status else None
        )

        if request.user.role == Role.STAFF and (
            credential_request.status in unverified_statuses
            or canonical_target in unverified_statuses
        ):
            return Response(
                {
                    "detail": (
                        "Staff cannot transition requests into or from "
                        "unverified statuses."
                    )
                },
                status=status.HTTP_403_FORBIDDEN
            )

        remarks = request.data.get('remarks', '')
        assigned_staff = request.data.get('assigned_staff')
        in_process_queue = request.data.get('in_process_queue')
        release_date = (
            request.data.get('release_date')
            or request.data.get('date_of_release')
        )

        if not new_status:
            return Response(
                {"detail": "status is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if release_date:
            from zoneinfo import ZoneInfo
            from datetime import datetime, date
            try:
                if isinstance(release_date, str):
                    clean_str = release_date.strip().split('T')[0]
                    parsed_dt = datetime.strptime(clean_str, '%Y-%m-%d').date()
                elif isinstance(release_date, datetime):
                    parsed_dt = release_date.date()
                elif isinstance(release_date, date):
                    parsed_dt = release_date
                else:
                    parsed_dt = None

                try:
                    today_manila = timezone.localdate()
                except Exception:
                    today_manila = (
                        timezone.now().astimezone(ZoneInfo('Asia/Manila')).date()
                    )

                if parsed_dt and parsed_dt < today_manila:
                    return Response(
                        {"detail": "Release date cannot be in the past."},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            except Exception:
                pass

        updated_request = CredentialRequestService.transition_request(
            actor=request.user,
            credential_request=credential_request,
            new_status=new_status,
            remarks=remarks,
            assigned_staff=assigned_staff,
            in_process_queue=in_process_queue,
            release_date=release_date
        )

        return Response(
            CredentialRequestSerializer(
                updated_request, context={'request': request}
            ).data
        )

    @extend_schema(responses={200: CredentialRequestSerializer})
    @action(
        detail=True, methods=['post', 'patch'],
        permission_classes=[IsAuthenticated]
    )
    def restore(self, request, pk=None):
        credential_request = self.get_object()
        remarks = request.data.get('remarks', '')
        updated_request = CredentialRequestService.restore_request(
            actor=request.user,
            credential_request=credential_request,
            remarks=remarks
        )
        return Response(
            CredentialRequestSerializer(
                updated_request, context={'request': request}
            ).data
        )

    @extend_schema(responses={200: CredentialRequestSerializer})
    @action(
        detail=True, methods=['post', 'patch'],
        permission_classes=[IsAuthenticated]
    )
    def reopen(self, request, pk=None):
        return self.restore(request, pk=pk)

    @extend_schema(responses={200: CredentialRequestSerializer})
    @action(
        detail=True, methods=['post'],
        permission_classes=[IsAuthenticated]
    )
    def approve(self, request, pk=None):
        credential_request = self.get_object()
        updated_request = CredentialRequestService.approve_request(
            actor=request.user,
            credential_request=credential_request
        )
        return Response(
            CredentialRequestSerializer(
                updated_request, context={'request': request}
            ).data,
            status=status.HTTP_200_OK
        )


class RequirementDocumentViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing requirement documents.
    """
    serializer_class = RequirementDocumentSerializer
    permission_classes = [RequirementDocumentPermission]
    parser_classes = [MultiPartParser, FormParser]

    def get_queryset(self):
        qs = RequirementDocument.objects.select_related(
            'request__user'
        ).order_by('-uploaded_at')
        user = self.request.user

        if user.is_authenticated and user.role == Role.STUDENT:
            return qs.filter(request__user=user)

        return qs

    @extend_schema(responses={201: RequirementDocumentSerializer})
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        document = RequirementDocumentService.upload_document(
            actor=request.user,
            validated_data=serializer.validated_data
        )
        headers = self.get_success_headers(serializer.data)
        return Response(
            RequirementDocumentSerializer(document).data,
            status=status.HTTP_201_CREATED,
            headers=headers
        )

    @action(detail=True, methods=['get'])
    def download(self, request, pk=None):
        document = self.get_object()

        if not document.file or not document.file.storage.exists(document.file.name):
            return Response(
                {"detail": "Document file not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        filename = Path(document.file.name).name
        return FileResponse(
            document.file.open('rb'),
            as_attachment=True,
            filename=filename
        )

    def update(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def partial_update(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def destroy(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)


class StudentClearanceViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing student clearances.
    """
    permission_classes = [StudentClearancePermission]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        qs = StudentClearance.objects.select_related('user').order_by('-updated_at')
        user = self.request.user

        if user.is_authenticated and user.role == Role.STUDENT:
            return qs.filter(user=user)

        return qs

    def get_serializer_class(self):
        if self.action == 'create':
            return StudentClearanceSubmitSerializer
        if self.action == 'review':
            return StudentClearanceReviewSerializer
        return StudentClearanceSerializer

    @extend_schema(responses={201: StudentClearanceSerializer})
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        clearance = StudentClearanceService.submit_clearance(
            actor=request.user,
            file=serializer.validated_data['file'],
            credential_request=serializer.validated_data.get('credential_request')
        )
        headers = self.get_success_headers(serializer.data)
        return Response(
            StudentClearanceSerializer(clearance).data,
            status=status.HTTP_201_CREATED,
            headers=headers
        )

    @extend_schema(responses={200: StudentClearanceSerializer})
    @action(detail=True, methods=['patch'])
    def review(self, request, pk=None):
        if request.user.role not in [Role.REGISTRAR, Role.ADMIN]:
            return Response(
                {
                    "detail": (
                        "Only Registrar Frontdesk and Admin can review clearances."
                    )
                },
                status=status.HTTP_403_FORBIDDEN
            )
        clearance = self.get_object()
        serializer = self.get_serializer(clearance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        updated_clearance = StudentClearanceService.review_clearance(
            actor=request.user,
            clearance=clearance,
            status=serializer.validated_data.get('status'),
            remarks=serializer.validated_data.get('remarks', '')
        )
        return Response(
            StudentClearanceSerializer(
                updated_clearance, context={'request': request}
            ).data
        )

    @action(detail=True, methods=['get'])
    def download(self, request, pk=None):
        clearance = self.get_object()

        # Strict Ownership Check for Download
        if request.user.role == Role.STUDENT and clearance.user != request.user:
            return Response(status=status.HTTP_403_FORBIDDEN)

        if not clearance.file or not clearance.file.storage.exists(clearance.file.name):
            return Response(
                {"detail": "File not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        filename = Path(clearance.file.name).name
        return FileResponse(
            clearance.file.open('rb'),
            as_attachment=True,
            filename=filename
        )

    def update(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def partial_update(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def destroy(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)


class PaymentViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing OTC payments.
    """
    serializer_class = PaymentSerializer
    permission_classes = [PaymentPermission]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        qs = Payment.objects.select_related(
            'request__user'
        ).order_by('-uploaded_at')
        user = self.request.user

        if user.is_authenticated and user.role == Role.STUDENT:
            return qs.filter(request__user=user)

        return qs

    @extend_schema(responses={201: PaymentSerializer})
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        req = serializer.validated_data['request']
        if request.user.role == Role.STUDENT and req.user != request.user:
            return Response(status=status.HTTP_403_FORBIDDEN)

        from django.db import IntegrityError
        try:
            payment = PaymentService.submit_payment(
                actor=request.user,
                request=req,
                amount=serializer.validated_data['amount'],
                receipt_image=serializer.validated_data['receipt_image'],
                receipt_reference_number=serializer.validated_data.get(
                    'receipt_reference_number', '')
            )
        except IntegrityError:
            return Response(
                {
                    "or_number": [
                        "This Official Receipt (O.R.) number is already in use."
                    ],
                    "receipt_reference_number": [
                        "This Official Receipt (O.R.) number is already in use."
                    ]
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        headers = self.get_success_headers(serializer.data)
        return Response(
            PaymentSerializer(payment, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
            headers=headers
        )

    @action(detail=True, methods=['get'])
    def download(self, request, pk=None):
        payment = self.get_object()

        if not payment.receipt_image or not payment.receipt_image.storage.exists(
            payment.receipt_image.name
        ):
            return Response(
                {"detail": "Receipt file not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        filename = Path(payment.receipt_image.name).name
        return FileResponse(
            payment.receipt_image.open('rb'),
            as_attachment=True,
            filename=filename
        )

    @extend_schema(responses={200: PaymentSerializer})
    @action(detail=True, methods=['patch'])
    def verify(self, request, pk=None):
        if request.user.role not in [Role.REGISTRAR, Role.ADMIN]:
            return Response(
                {
                    "detail": (
                        "Only Registrar Frontdesk and Admin can verify payments."
                    )
                },
                status=status.HTTP_403_FORBIDDEN
            )
        payment = self.get_object()

        action_type = request.data.get('action')
        remarks = request.data.get('remarks', '')

        if not action_type:
            return Response(
                {"detail": "action is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        updated_payment = PaymentService.verify_payment(
            actor=request.user,
            payment=payment,
            action=action_type,
            remarks=remarks
        )

        return Response(
            PaymentSerializer(updated_payment, context={'request': request}).data
        )

    def update(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def partial_update(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def destroy(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)


class AdminDailyForecastView(APIView):
    """
    Daily incoming credential request forecasting.
    Restricted to Staff, Registrars, and Administrators.
    """
    permission_classes = [IsAuthenticated]

    @staticmethod
    def _compute_default_start_date():
        from zoneinfo import ZoneInfo
        from datetime import timedelta
        try:
            base_date = timezone.localdate()
        except Exception:
            base_date = timezone.now().astimezone(ZoneInfo('Asia/Manila')).date()
        cur = base_date + timedelta(days=1)
        while cur.weekday() >= 5:
            cur += timedelta(days=1)
        return cur.strftime('%Y-%m-%d')

    def get(self, request):
        if request.user.role not in [Role.STAFF, Role.REGISTRAR, Role.ADMIN]:
            return Response(
                {
                    "detail": (
                        "Only staff and administrators can access daily "
                        "demand forecasting."
                    )
                },
                status=status.HTTP_403_FORBIDDEN
            )

        start_date = request.query_params.get('start_date')
        if not start_date:
            start_date = self._compute_default_start_date()

        op_days = int(request.query_params.get('operating_days', 20))
        res = MLClient.forecast_daily_demand(
            start_date=start_date, operating_days=op_days
        )
        if isinstance(res, dict) and 'next_operating_day' not in res:
            try:
                from datetime import datetime
                s_dt = datetime.strptime(start_date, '%Y-%m-%d')
                res['next_operating_day'] = s_dt.strftime('%A')
                res['next_operating_date'] = start_date
            except Exception:
                pass
        return Response(res, status=status.HTTP_200_OK)

    def post(self, request):
        if request.user.role not in [Role.STAFF, Role.REGISTRAR, Role.ADMIN]:
            return Response(
                {
                    "detail": (
                        "Only staff and administrators can access daily "
                        "demand forecasting."
                    )
                },
                status=status.HTTP_403_FORBIDDEN
            )

        start_date = request.data.get('start_date')
        if not start_date:
            start_date = self._compute_default_start_date()

        op_days = int(request.data.get('operating_days', 20))
        res = MLClient.forecast_daily_demand(
            start_date=start_date, operating_days=op_days
        )
        if isinstance(res, dict) and 'next_operating_day' not in res:
            try:
                from datetime import datetime
                s_dt = datetime.strptime(start_date, '%Y-%m-%d')
                res['next_operating_day'] = s_dt.strftime('%A')
                res['next_operating_date'] = start_date
            except Exception:
                pass
        return Response(res, status=status.HTTP_200_OK)


class AdminMonthlyWorkloadView(APIView):
    """
    Monthly workload volume forecasting and classification.
    Restricted to Staff, Registrars, and Administrators.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role not in [Role.STAFF, Role.REGISTRAR, Role.ADMIN]:
            return Response(
                {
                    "detail": (
                        "Only staff and administrators can access monthly "
                        "workload forecasting."
                    )
                },
                status=status.HTTP_403_FORBIDDEN
            )

        target_month = request.query_params.get('target_month')
        res = MLClient.forecast_monthly_workload(target_month=target_month)
        return Response(res, status=status.HTTP_200_OK)

    def post(self, request):
        if request.user.role not in [Role.STAFF, Role.REGISTRAR, Role.ADMIN]:
            return Response(
                {
                    "detail": (
                        "Only staff and administrators can access monthly "
                        "workload forecasting."
                    )
                },
                status=status.HTTP_403_FORBIDDEN
            )

        target_month = request.data.get('target_month')
        res = MLClient.forecast_monthly_workload(target_month=target_month)
        return Response(res, status=status.HTTP_200_OK)


class MLHealthStatusView(APIView):
    """
    Health and status check for ML microservice integration.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(MLClient.get_health(), status=status.HTTP_200_OK)


class RegistrarApprovalSettingsView(APIView):
    """
    GET /api/settings/registrar-approval/
    PATCH /api/settings/registrar-approval/
    Allows Registrar and Admin to view and toggle auto-approval.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: RegistrarSettingsSerializer})
    def get(self, request):
        settings_obj = RegistrarSettings.get_settings()
        serializer = RegistrarSettingsSerializer(
            settings_obj, context={'request': request}
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        request=RegistrarSettingsSerializer,
        responses={200: RegistrarSettingsSerializer}
    )
    def patch(self, request):
        if request.user.role not in [Role.REGISTRAR, Role.ADMIN]:
            raise PermissionDenied(
                "Only Registrar or Admin can modify approval settings."
            )

        settings_obj = RegistrarSettings.get_settings()
        prev_val = settings_obj.auto_approve_requests
        auto_approve = request.data.get('auto_approve_requests')
        if auto_approve is None:
            auto_approve = request.data.get('auto_approve')

        if auto_approve is not None:
            if isinstance(auto_approve, str):
                settings_obj.auto_approve_requests = auto_approve.lower() in [
                    'true', '1', 'yes'
                ]
            else:
                settings_obj.auto_approve_requests = bool(auto_approve)

        if 'default_signatory_name' in request.data:
            settings_obj.default_signatory_name = str(
                request.data['default_signatory_name']
            ).strip()
        elif request.user.role == Role.REGISTRAR:
            full_name = (
                f"{request.user.first_name} {request.user.last_name}".strip()
            )
            actor_name = full_name or request.user.username
            if actor_name:
                settings_obj.default_signatory_name = actor_name
        if 'default_signatory_title' in request.data:
            settings_obj.default_signatory_title = str(
                request.data['default_signatory_title']
            ).strip()

        settings_obj.updated_by = request.user
        settings_obj.save()

        AuditService.log_action(
            actor=request.user,
            action='REGISTRAR_SETTINGS_UPDATED',
            object_type='RegistrarSettings',
            object_id=settings_obj.id,
            previous_state={'auto_approve_requests': prev_val},
            new_state={
                'auto_approve_requests': settings_obj.auto_approve_requests
            }
        )

        serializer = RegistrarSettingsSerializer(
            settings_obj, context={'request': request}
        )
        return Response(serializer.data, status=status.HTTP_200_OK)
