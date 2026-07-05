from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class AuditLog(models.Model):
    """
    Immutable audit log recording any business-state mutations.
    """
    actor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="User who performed the action"
    )
    action = models.CharField(
        max_length=255,
        help_text="The action performed (e.g., CREATE_REQUEST, VERIFY_PAYMENT)"
    )
    object_type = models.CharField(
        max_length=100,
        help_text="The model name of the object being modified"
    )
    object_id = models.CharField(
        max_length=255,
        help_text="The primary key of the object being modified"
    )
    previous_state = models.JSONField(
        null=True,
        blank=True,
        help_text="State of the object before the action"
    )
    new_state = models.JSONField(
        null=True,
        blank=True,
        help_text="State of the object after the action"
    )
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    metadata = models.JSONField(
        null=True,
        blank=True,
        help_text="Optional contextual metadata"
    )

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return (
            f"{self.timestamp} - {self.action} "
            f"on {self.object_type} {self.object_id}"
        )
