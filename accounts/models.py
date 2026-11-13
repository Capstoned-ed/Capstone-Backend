import uuid
from django.conf import settings
from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Role(models.TextChoices):
    STUDENT = 'student', _('Student')
    STAFF = 'staff', _('Staff')
    REGISTRAR = 'registrar', _('Registrar')
    ADMIN = 'admin', _('Admin')


class CustomUserManager(UserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', Role.ADMIN)

        return self._create_user(username, email, password, **extra_fields)


class User(AbstractUser):
    """
    Custom User model following the institution-managed account pattern.
    Public registration is disabled. Users are provisioned by Admins.
    """
    objects = CustomUserManager()

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.STUDENT,
        help_text=_('Designates the role of the user within the system.'),
    )
    force_password_change = models.BooleanField(
        default=False,
        help_text=_(
            'Designates whether the user must change their password '
            'upon next login.'
        ),
    )
    course_name = models.CharField(
        max_length=150,
        blank=True,
        default='Bachelor of Science in Information Technology',
        help_text=_(
            'Full name of enrolled program '
            '(e.g., Bachelor of Science in Information Technology).'
        ),
    )
    course_code = models.CharField(
        max_length=20,
        blank=True,
        default='IT',
        help_text=_('Acronym or short code of enrolled program (e.g., IT).'),
    )
    birth_date = models.DateField(
        null=True,
        blank=True,
        help_text=_('Student date of birth.'),
    )
    contact_number = models.CharField(
        max_length=30,
        blank=True,
        default='',
        help_text=_('Active contact or mobile number.'),
    )
    year_level = models.CharField(
        max_length=30,
        blank=True,
        default='1st year',
        help_text=_('Academic year level (e.g., 1st year, Alumnus).'),
    )

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"


class PasswordResetOTP(models.Model):
    """
    Stores cryptographically hashed one-time passwords for password recovery.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='password_reset_otps'
    )
    otp_hash = models.CharField(max_length=128)
    attempts = models.PositiveSmallIntegerField(default=0)
    is_used = models.BooleanField(default=False)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_used']),
            models.Index(fields=['expires_at']),
        ]

    def __str__(self):
        return f"OTP for {self.user.username} (used={self.is_used})"

    def is_valid(self):
        return (
            not self.is_used and
            timezone.now() <= self.expires_at and
            self.attempts < 5
        )
