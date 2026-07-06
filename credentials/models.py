from django.db import models


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
