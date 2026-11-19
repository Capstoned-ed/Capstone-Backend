from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction

from audit.services import AuditService
from notifications.models import NotificationEvent
from notifications.services import NotificationService

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
        if actor and getattr(actor, 'id', None) and getattr(user, 'id', None):
            if str(actor.id) == str(user.id):
                if 'role' in validated_data and validated_data['role'] != user.role:
                    raise ValidationError(
                        "You cannot change your own administrative role."
                    )
                if 'is_active' in validated_data and not validated_data['is_active']:
                    raise ValidationError(
                        "You cannot deactivate your own administrative account."
                    )

        previous_state = {
            'username': user.username,
            'email': user.email,
            'role': user.role,
            'is_active': user.is_active,
        }

        data = validated_data.copy()
        if 'password' in data:
            raw_password = data.pop('password')
            if raw_password:
                user.set_password(raw_password)

        for attr, value in data.items():
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
    def update_user_profile(user, data):
        """
        Updates basic profile fields (first_name, last_name, email) for the user.
        """
        for field in ['first_name', 'last_name', 'email']:
            if field in data:
                setattr(user, field, data[field])
        user.save()
        return user

    @staticmethod
    @transaction.atomic
    def change_password(user, current_password, new_password):
        """
        Verifies current password, sets hashed new password,
        resets force_password_change, and logs audit action.
        """
        if not user.check_password(current_password):
            raise ValidationError("Current password is incorrect.")

        if current_password == new_password:
            raise ValidationError(
                "New password must be different from your current password."
            )

        user.set_password(new_password)
        user.force_password_change = False
        user.save(update_fields=['password', 'force_password_change'])

        AuditService.log_action(
            actor=user,
            action='PASSWORD_CHANGED',
            object_type='User',
            object_id=user.id,
            previous_state={'force_password_change': True},
            new_state={'force_password_change': False}
        )
        return user

    @staticmethod
    @transaction.atomic
    def deactivate_user(actor, user):
        """
        Soft deletes the user by setting is_active to False.
        """
        if actor and getattr(actor, 'id', None) and getattr(user, 'id', None):
            if str(actor.id) == str(user.id):
                raise ValidationError(
                    "You cannot deactivate your own administrative account."
                )

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

