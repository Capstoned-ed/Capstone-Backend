from django.db import models
from django.contrib.auth import get_user_model
import uuid

User = get_user_model()


class NotificationEvent(models.TextChoices):
    ACCOUNT_CREATED = 'ACCOUNT_CREATED', 'Account Created'
    PASSWORD_RESET = 'PASSWORD_RESET', 'Password Reset'
    REQUEST_CREATED = 'REQUEST_CREATED', 'Request Created'
    REQUEST_STATUS_CHANGED = 'REQUEST_STATUS_CHANGED', 'Request Status Changed'
    CLEARANCE_SUBMITTED = 'CLEARANCE_SUBMITTED', 'Clearance Submitted'
    CLEARANCE_APPROVED = 'CLEARANCE_APPROVED', 'Clearance Approved'
    CLEARANCE_REJECTED = 'CLEARANCE_REJECTED', 'Clearance Rejected'
    PAYMENT_SUBMITTED = 'PAYMENT_SUBMITTED', 'Payment Submitted'
    PAYMENT_VERIFIED = 'PAYMENT_VERIFIED', 'Payment Verified'
    PAYMENT_REJECTED = 'PAYMENT_REJECTED', 'Payment Rejected'


class Notification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='notifications'
    )
    # max_length=50 accommodates longest choice value (REQUEST_STATUS_CHANGED, 22 chars)
    event_type = models.CharField(max_length=50, choices=NotificationEvent.choices)
    message = models.TextField()
    related_object_type = models.CharField(max_length=100, null=True, blank=True)
    related_object_id = models.CharField(max_length=255, null=True, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['user', 'is_read']),
        ]

    def __str__(self):
        return f"[{self.event_type}] for {self.user.username}"
