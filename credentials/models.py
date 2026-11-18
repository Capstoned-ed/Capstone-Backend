import uuid
from django.db import models, transaction
from django.conf import settings
from django.utils import timezone
from .validators import validate_file_size, validate_file_extension, validate_mime_type
from .storage import private_storage


DEFAULT_DOC_CODES = {
    'TOR': '1',
    'HONORABLE DISMISSAL': '2',
    'HONORABLE_DISMISSAL': '2',
    'HD': '2',
    'EVALUATION': '5',
    'EVAL': '5',
    'CERTIFICATION': '4',
    'CERT': '4',
    'CAR': '4f',
    'CERT_CAR': '4f',
    'GPA': '4b',
    'CERT_GPA': '4b',
    'OFFICIALLY ENROLLED': '4a',
    'OFFICIALLY_ENROLLED': '4a',
    'COE': '4a',
    'CERT_ENROLLED': '4a',
    'EARNED UNITS': '4d',
    'EARNED_UNITS': '4d',
    'UNITS': '4d',
    'CERT_UNITS': '4d',
    'SUB WITH GRADES': '4g',
    'SUB_WITH_GRADES': '4g',
    'GRADES': '4g',
    'CERT_GRADES': '4g',
    'AUTH': '10',
    'AUTHENTICATION': '10',
    'ENDORSE': '4m',
    'ENDORSEMENT': '4m',
}


class RegistrarSettings(models.Model):
    """
    Singleton system setting for Registrar auto-approval and signatory tracking.
    """
    auto_approve_requests = models.BooleanField(
        default=True,
        help_text=(
            "When True, requests are automatically approved on behalf of the "
            "Registrar. When False, requests pause for manual Registrar approval."
        )
    )
    default_signatory_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Default signatory name if no dynamic Registrar is configured."
    )
    default_signatory_title = models.CharField(
        max_length=255,
        blank=True,
        default="University Registrar",
        help_text="Signatory title (e.g., University Registrar)."
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='updated_registrar_settings'
    )

    class Meta:
        verbose_name = "Registrar Settings"
        verbose_name_plural = "Registrar Settings"

    @classmethod
    def get_settings(cls):
        obj, _ = cls.objects.get_or_create(id=1)
        return obj

    @classmethod
    def get_active_signatory(cls, actor=None):
        settings_obj = cls.get_settings()
        from accounts.models import User, Role

        def _format_user_name(u):
            first = getattr(u, 'first_name', '') or ''
            last = getattr(u, 'last_name', '') or ''
            return f"{first} {last}".strip() or getattr(u, 'username', '')

        # 1. Currently authenticated Registrar user (live session signatory)
        if actor and getattr(actor, 'is_authenticated', False):
            is_active_reg = (
                getattr(actor, 'role', None) == Role.REGISTRAR
                and getattr(actor, 'is_active', True)
            )
            if is_active_reg:
                return _format_user_name(actor), actor

        # 2. Registrar who most recently updated RegistrarSettings
        updated_by = getattr(settings_obj, 'updated_by', None)
        if (
            updated_by
            and getattr(updated_by, 'role', None) == Role.REGISTRAR
            and getattr(updated_by, 'is_active', True)
        ):
            return _format_user_name(updated_by), updated_by

        # 3. Most recently logged-in active Registrar account in DB
        reg_user = (
            User.objects.filter(role=Role.REGISTRAR, is_active=True)
            .order_by('-last_login', 'id')
            .first()
        )
        if reg_user:
            return _format_user_name(reg_user), reg_user

        # 4. Configured signatory name fallback (never hardcoded to a specific person)
        configured = (settings_obj.default_signatory_name or '').strip()
        if configured:
            return configured, None
        return "University Registrar", None

    def __str__(self):
        return f"Registrar Settings (auto_approve={self.auto_approve_requests})"


class CredentialType(models.Model):
    """
    Master data representing the types of credentials that can be requested.
    Managed by Admins and Registrars.
    """
    code = models.CharField(
        max_length=10,
        unique=True,
        help_text="Unique short code (e.g., TOR, COE)."
    )
    doc_code = models.CharField(
        max_length=10,
        blank=True,
        default='',
        help_text="Document code used for tracking number (e.g. 1, 2, 4A, 4F, 5)."
    )
    name = models.CharField(
        max_length=100,
        help_text="Full name of the credential type."
    )
    description = models.TextField(
        blank=True,
        help_text="Description of the credential."
    )
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Fixed price for this credential."
    )
    processing_days = models.PositiveIntegerField(
        help_text="Estimated processing time in days."
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this credential type is currently offered."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.doc_code:
            code_upper = self.code.upper() if self.code else ''
            name_upper = self.name.upper() if self.name else ''
            self.doc_code = (
                DEFAULT_DOC_CODES.get(code_upper) or
                DEFAULT_DOC_CODES.get(name_upper) or
                self.code
            )
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.code} - {self.name}"


class RequestStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    REQUIREMENTS_VERIFICATION = 'REQUIREMENTS_VERIFICATION', 'Requirements Verification'
    REQUIREMENTS_REJECTED = 'REQUIREMENTS_REJECTED', 'Requirements Rejected'
    PAYMENT_PENDING = 'PAYMENT_PENDING', 'Payment Pending'
    PAYMENT_VERIFIED = 'PAYMENT_VERIFIED', 'Payment Verified'
    PROCESSING = 'PROCESSING', 'Processing'
    READY_FOR_RELEASE = 'READY_FOR_RELEASE', 'Ready for Release'
    RELEASED = 'RELEASED', 'Released'
    REJECTED = 'REJECTED', 'Rejected'
    CANCELLED = 'CANCELLED', 'Cancelled'


class CredentialRequest(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='credential_requests'
    )
    credential_type = models.ForeignKey(
        CredentialType,
        on_delete=models.PROTECT,
        related_name='requests'
    )
    assigned_staff = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_credential_requests'
    )
    in_process_queue = models.BooleanField(
        default=False,
        help_text="Designates whether request is in active processing queue."
    )
    status = models.CharField(
        max_length=50,
        choices=RequestStatus.choices,
        default=RequestStatus.PENDING
    )
    course = models.CharField(
        max_length=20,
        blank=True,
        help_text="Course acronym captured at the time of request."
    )
    tracking_number = models.CharField(max_length=50, unique=True, editable=False)
    remarks = models.TextField(blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_credential_requests',
        help_text="Registrar or Admin user who approved this request."
    )
    approved_by_name = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text="Name and title of the approving registrar/official."
    )
    approved_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp of registrar approval."
    )
    is_approved = models.BooleanField(
        default=False,
        help_text="Flag indicating whether request has received registrar approval."
    )
    is_auto_approved = models.BooleanField(
        default=False,
        help_text="Flag indicating whether approval was granted automatically."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['user']),
            models.Index(fields=['tracking_number']),
            models.Index(fields=['assigned_staff']),
            models.Index(fields=['in_process_queue']),
        ]

    def save(self, *args, **kwargs):
        if not self.course:
            self.course = getattr(self.user, 'course_code', None) or 'IT'

        if not self.tracking_number:
            date_str = timezone.now().strftime('%y-%m-%d')
            username = str(self.user.username) if self.user else 'STUDENT'
            student_id = username[2:] if len(username) > 2 else username

            if hasattr(self, '_custom_doc_code') and self._custom_doc_code:
                doc_num = str(self._custom_doc_code)
            elif self.credential_type:
                doc_num = (
                    self.credential_type.doc_code or
                    DEFAULT_DOC_CODES.get(self.credential_type.code.upper()) or
                    DEFAULT_DOC_CODES.get(self.credential_type.name.upper()) or
                    self.credential_type.code
                )
            else:
                doc_num = '1'

            with transaction.atomic():
                user_requests_count = (
                    CredentialRequest.objects.select_for_update()
                    .filter(user=self.user)
                    .exclude(pk=self.pk)
                    .count()
                )
                user_seq = user_requests_count + 1
                seq_str = f"{user_seq:03d}"
                self.tracking_number = (
                    f"{self.course}-{date_str}-{student_id}-{doc_num}-{seq_str}"
                )

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.tracking_number} - {self.status}"


def private_upload_path(subfolder, target_id, filename):
    ext = filename.split('.')[-1] if '.' in filename else ''
    new_filename = f"{uuid.uuid4().hex}.{ext}" if ext else uuid.uuid4().hex
    return f"{subfolder}/{target_id}/{new_filename}"


def document_upload_path(instance, filename):
    return private_upload_path("requests", instance.request.id, filename)


class RequirementDocument(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request = models.ForeignKey(
        CredentialRequest,
        on_delete=models.CASCADE,
        related_name='documents'
    )
    document_type = models.CharField(
        max_length=50,
        help_text="Type of document (e.g., ID, CLEARANCE)."
    )
    file = models.FileField(
        upload_to=document_upload_path,
        storage=private_storage,
        validators=[validate_file_size, validate_file_extension, validate_mime_type]
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.document_type} for {self.request.tracking_number}"


class ClearanceStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    APPROVED = 'APPROVED', 'Approved'
    REJECTED = 'REJECTED', 'Rejected'


def clearance_upload_path(instance, filename):
    return private_upload_path("clearances", instance.user.id, filename)


class StudentClearance(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='clearances'
    )
    credential_request = models.ForeignKey(
        'CredentialRequest',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='clearance_records'
    )
    status = models.CharField(
        max_length=50,
        choices=ClearanceStatus.choices,
        default=ClearanceStatus.PENDING
    )
    file = models.FileField(
        upload_to=clearance_upload_path,
        storage=private_storage,
        validators=[validate_file_size, validate_file_extension, validate_mime_type]
    )
    remarks = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_clearances'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Clearance for {self.user.username} - {self.status}"


class PaymentStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    VERIFIED = 'VERIFIED', 'Verified'
    REJECTED = 'REJECTED', 'Rejected'


def receipt_upload_path(instance, filename):
    ext = filename.split('.')[-1] if '.' in filename else ''
    filename = f"{uuid.uuid4().hex}.{ext}" if ext else uuid.uuid4().hex
    return f"payments/{instance.request.id}/{filename}"


class Payment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request = models.ForeignKey(
        CredentialRequest,
        on_delete=models.CASCADE,
        related_name='payments'
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    receipt_reference_number = models.CharField(max_length=100, blank=True)
    receipt_image = models.FileField(
        upload_to=receipt_upload_path,
        storage=private_storage,
        validators=[validate_file_size, validate_file_extension, validate_mime_type]
    )
    status = models.CharField(
        max_length=50,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING
    )
    remarks = models.TextField(blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verified_payments'
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['request', 'status']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"Payment {self.id} for {self.request.tracking_number}"
