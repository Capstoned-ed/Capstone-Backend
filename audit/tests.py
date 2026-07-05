import pytest
from django.contrib.auth import get_user_model
from audit.services import AuditService
from accounts.models import Role

User = get_user_model()


@pytest.fixture
def admin_user():
    return User.objects.create_user(
        username='admin_audit',
        email='admin_audit@test.com',
        password='password',
        role=Role.ADMIN
    )


@pytest.mark.django_db
def test_audit_service_log_action(admin_user):
    log = AuditService.log_action(
        actor=admin_user,
        action='TEST_ACTION',
        object_type='TestModel',
        object_id='123',
        previous_state={'status': 'PENDING'},
        new_state={'status': 'VERIFIED'},
        metadata={'ip': '127.0.0.1'}
    )

    assert log.id is not None
    assert log.actor == admin_user
    assert log.action == 'TEST_ACTION'
    assert log.object_type == 'TestModel'
    assert log.object_id == '123'
    assert log.previous_state == {'status': 'PENDING'}
    assert log.new_state == {'status': 'VERIFIED'}
    assert log.metadata == {'ip': '127.0.0.1'}
    assert log.timestamp is not None

    # Test __str__ method
    assert 'TEST_ACTION' in str(log)


@pytest.mark.django_db
def test_audit_service_minimal_fields():
    log = AuditService.log_action(
        actor=None,
        action='SYSTEM_ACTION',
        object_type='System',
        object_id='0'
    )

    assert log.id is not None
    assert log.actor is None
    assert log.action == 'SYSTEM_ACTION'
    assert log.previous_state is None
    assert log.new_state is None
    assert log.metadata is None
