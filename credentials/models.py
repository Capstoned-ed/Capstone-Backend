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
    'CERTIFICATION': '4',
    'CAR': '4F',
    'CERT_CAR': '4F',
    'GPA': '4B',
    'CERT_GPA': '4B',
    'OFFICIALLY ENROLLED': '4A',
    'OFFICIALLY_ENROLLED': '4A',
    'CERT_ENROLLED': '4A',
    'EARNED UNITS': '4D',
    'EARNED_UNITS': '4D',
    'CERT_UNITS': '4D',
    'SUB WITH GRADES': '4G',
    'SUB_WITH_GRADES': '4G',
    'CERT_GRADES': '4G',
}


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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['user']),
            models.Index(fields=['tracking_number']),
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
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='clearance'
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
