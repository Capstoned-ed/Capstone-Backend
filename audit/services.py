from .models import AuditLog


class AuditService:
    @staticmethod
    def log_action(
        actor,
        action,
        object_type,
        object_id,
        previous_state=None,
        new_state=None,
        metadata=None
    ):
        """
        Creates a new AuditLog entry.
        Should be called exclusively by other Service Layer classes.
        """
        return AuditLog.objects.create(
            actor=actor,
            action=action,
            object_type=object_type,
            object_id=str(object_id),
            previous_state=previous_state,
            new_state=new_state,
            metadata=metadata
        )
