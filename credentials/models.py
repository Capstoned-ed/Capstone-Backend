import uuid
from django.db import models, transaction
from django.conf import settings
from django.utils import timezone
from .validators import validate_file_size, validate_file_extension, validate_mime_type


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
    tracking_number = models.CharField(max_length=20, unique=True, editable=False)
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
        if not self.tracking_number:
            year = timezone.now().year

            with transaction.atomic():
                last_request = CredentialRequest.objects.select_for_update().filter(
                    tracking_number__startswith=f'REQ-{year}-'
                ).order_by('-tracking_number').first()

                if last_request:
                    last_sequence = int(last_request.tracking_number.split('-')[-1])
                    new_sequence = last_sequence + 1
                else:
                    new_sequence = 1

                self.tracking_number = f'REQ-{year}-{new_sequence:06d}'

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.tracking_number} - {self.status}"


def document_upload_path(instance, filename):
    ext = filename.split('.')[-1] if '.' in filename else ''
    filename = f"{uuid.uuid4().hex}.{ext}" if ext else uuid.uuid4().hex
    return f"requests/{instance.request.id}/{filename}"


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
        validators=[validate_file_size, validate_file_extension, validate_mime_type]
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.document_type} for {self.request.tracking_number}"
