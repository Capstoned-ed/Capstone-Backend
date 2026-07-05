from django.contrib.auth import get_user_model
from django.db import transaction
from audit.services import AuditService

User = get_user_model()


class AccountService:
    @staticmethod
    @transaction.atomic
    def create_user(actor, username, email, password, role):
        """
        Creates a new user, forces password change, and logs the action.
        """
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            role=role,
            force_password_change=True
        )

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
                'is_active': user.is_active,
                'force_password_change': user.force_password_change
            }
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
