import logging
import secrets
from datetime import timedelta
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password, check_password
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from audit.services import AuditService
from notifications.services import NotificationService
from notifications.models import NotificationEvent
from .models import PasswordResetOTP

logger = logging.getLogger(__name__)

User = get_user_model()


class AccountService:
    @staticmethod
    @transaction.atomic
    def create_user(
        actor, username, email, password, role,
        course_name=None, course_code=None, **extra_fields
    ):
        """
        Creates a new user, forces password change, and logs the action.
        """
        user_kwargs = {
            'username': username,
            'email': email,
            'password': password,
            'role': role,
            'force_password_change': True,
            **extra_fields
        }
        if course_name is not None:
            user_kwargs['course_name'] = course_name
        if course_code is not None:
            user_kwargs['course_code'] = course_code

        user = User.objects.create_user(**user_kwargs)

        # Log the action
        AuditService.log_action(
            actor=actor,
            action='USER_CREATED',
            object_type='User',
            object_id=user.id,
            previous_state=None,
            new_state={
                'username': user.username,
                'email': user.email,
                'role': user.role,
                'course_name': user.course_name,
                'course_code': user.course_code,
                'is_active': user.is_active,
                'force_password_change': user.force_password_change
            }
        )

        NotificationService.create_notification(
            recipient=user,
            event_type=NotificationEvent.ACCOUNT_CREATED,
            message=(
                "Your account has been provisioned. "
                "Please update your temporary password."
            ),
            related_object_type='User',
            related_object_id=str(user.id)
        )

        return user

    @staticmethod
    @transaction.atomic
    def update_user(actor, user, validated_data):
        """
        Updates an existing user and logs the action.
        """
        previous_state = {
            'username': user.username,
            'email': user.email,
            'role': user.role,
            'is_active': user.is_active,
        }

        for attr, value in validated_data.items():
            setattr(user, attr, value)

        user.save()

        new_state = {
            'username': user.username,
            'email': user.email,
            'role': user.role,
            'is_active': user.is_active,
        }

        if previous_state != new_state:
            AuditService.log_action(
                actor=actor,
                action='USER_UPDATED',
                object_type='User',
                object_id=user.id,
                previous_state=previous_state,
                new_state=new_state
            )

        return user

    @staticmethod
    @transaction.atomic
    def deactivate_user(actor, user):
        """
        Soft deletes the user by setting is_active to False.
        """
        previous_state = {'is_active': user.is_active}
        user.is_active = False
        user.save(update_fields=['is_active'])

        AuditService.log_action(
            actor=actor,
            action='USER_DEACTIVATED',
            object_type='User',
            object_id=user.id,
            previous_state=previous_state,
            new_state={'is_active': False}
        )
        return user


class PasswordResetService:
    """
    Handles secure OTP generation, verification, and password reset flows.
    """

    @staticmethod
    def mask_email(email):
        if not email or '@' not in email:
            return email
        local, domain = email.split('@', 1)
        if len(local) <= 2:
            masked_local = f"{local[0]}*" if local else "**"
        else:
            masked_local = f"{local[:2]}{'*' * max(2, len(local) - 3)}{local[-1]}"
        return f"{masked_local}@{domain}"

    @classmethod
    @transaction.atomic
    def request_otp(cls, email_or_identifier):
        """
        Generates and sends a 6-digit OTP to the user's registered email.
        Always returns generic message for anti-enumeration security.
        """
        clean_id = (email_or_identifier or '').strip()
        generic_msg = (
            "If an account with that email or ID exists, "
            "a verification code has been sent."
        )

        if not clean_id:
            return {'detail': generic_msg, 'masked_email': ''}

        user = (
            User.objects.filter(email__iexact=clean_id).first() or
            User.objects.filter(username__iexact=clean_id).first()
        )

        if not user or not user.is_active or not user.email:
            return {'detail': generic_msg, 'masked_email': ''}

        # Rate limit cooldown: don't regenerate if active OTP created within 60s
        recent_otp = (
            PasswordResetOTP.objects.filter(
                user=user,
                is_used=False,
                created_at__gte=timezone.now() - timedelta(seconds=60)
            )
            .first()
        )
        masked_email = cls.mask_email(user.email)
        if recent_otp:
            return {'detail': generic_msg, 'masked_email': masked_email}

        # Invalidate any previously unused OTPs for this user
        PasswordResetOTP.objects.filter(user=user, is_used=False).update(
            is_used=True
        )

        # Generate cryptographically secure 6-digit numeric OTP
        otp_code = f"{secrets.randbelow(1000000):06d}"
        expires_at = timezone.now() + timedelta(minutes=10)

        PasswordResetOTP.objects.create(
            user=user,
            otp_hash=make_password(otp_code),
            expires_at=expires_at
        )

        # Send email
        subject = f"RegQuest - Your Verification Code is {otp_code}"
        name = user.first_name or user.username
        message = (
            f"Hello {name},\n\n"
            f"Your password reset verification code is: {otp_code}\n\n"
            "This code will expire in 10 minutes.\n"
            "If you did not request this password reset, please ignore this email.\n\n"
            "— RegQuest Academic Credential Management System"
        )

        try:
            send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=False,
            )
        except Exception as exc:
            logger.error(
                "Failed to send password reset OTP email to %s: %s",
                user.email,
                exc,
                exc_info=True,
            )

        AuditService.log_action(
            actor=user,
            action='PASSWORD_RESET_REQUESTED',
            object_type='User',
            object_id=user.id,
            previous_state=None,
            new_state={'email': user.email}
        )

        return {'detail': generic_msg, 'masked_email': masked_email}

    @classmethod
    def verify_otp(cls, email_or_identifier, otp):
        """
        Validates OTP code without resetting password.
        """
        clean_id = (email_or_identifier or '').strip()
        clean_otp = (otp or '').strip()

        if not clean_id or len(clean_otp) != 6:
            raise ValidationError("Invalid or expired verification code.")

        user = (
            User.objects.filter(email__iexact=clean_id).first() or
            User.objects.filter(username__iexact=clean_id).first()
        )

        if not user or not user.is_active:
            raise ValidationError("Invalid or expired verification code.")

        active_otps = list(
            PasswordResetOTP.objects.filter(
                user=user,
                is_used=False,
                expires_at__gte=timezone.now(),
                attempts__lt=5
            )
            .order_by('-created_at')
        )

        if not active_otps:
            raise ValidationError("Invalid or expired verification code.")

        matched_otp = None
        for otp_record in active_otps:
            if check_password(clean_otp, otp_record.otp_hash):
                matched_otp = otp_record
                break

        if not matched_otp:
            latest = active_otps[0]
            latest.attempts += 1
            if latest.attempts >= 5:
                latest.is_used = True
            latest.save(update_fields=['attempts', 'is_used'])
            raise ValidationError("Invalid verification code.")

        return True

    @classmethod
    @transaction.atomic
    def reset_password(cls, email_or_identifier, otp, new_password):
        """
        Verifies OTP and resets the user's password.
        """
        clean_id = (email_or_identifier or '').strip()
        clean_otp = (otp or '').strip()
        clean_password = (new_password or '').strip()

        if len(clean_password) < 6:
            raise ValidationError(
                "Password must be at least 6 characters long."
            )

        if not clean_id or len(clean_otp) != 6:
            raise ValidationError("Invalid or expired verification code.")

        user = (
            User.objects.filter(email__iexact=clean_id).first() or
            User.objects.filter(username__iexact=clean_id).first()
        )

        if not user or not user.is_active:
            raise ValidationError("Invalid or expired verification code.")

        active_otps = list(
            PasswordResetOTP.objects.select_for_update()
            .filter(
                user=user,
                is_used=False,
                expires_at__gte=timezone.now(),
                attempts__lt=5
            )
            .order_by('-created_at')
        )

        if not active_otps:
            raise ValidationError("Invalid or expired verification code.")

        matched_otp = None
        for otp_record in active_otps:
            if check_password(clean_otp, otp_record.otp_hash):
                matched_otp = otp_record
                break

        if not matched_otp:
            latest = active_otps[0]
            latest.attempts += 1
            if latest.attempts >= 5:
                latest.is_used = True
            latest.save(update_fields=['attempts', 'is_used'])
            raise ValidationError("Invalid verification code.")

        # Invalidate all active OTPs for this user
        PasswordResetOTP.objects.filter(user=user, is_used=False).update(
            is_used=True
        )

        # Update password
        user.set_password(clean_password)
        user.force_password_change = False
        user.save(update_fields=['password', 'force_password_change'])

        AuditService.log_action(
            actor=user,
            action='PASSWORD_RESET_COMPLETED',
            object_type='User',
            object_id=user.id,
            previous_state=None,
            new_state={'password_reset': True}
        )

        NotificationService.create_notification(
            recipient=user,
            event_type=NotificationEvent.PASSWORD_RESET,
            message="Your password was reset successfully.",
            related_object_type='User',
            related_object_id=str(user.id)
        )

        return user
