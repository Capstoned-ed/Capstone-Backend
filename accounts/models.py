from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models
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

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"
