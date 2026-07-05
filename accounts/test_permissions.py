import pytest
from unittest.mock import Mock
from accounts.models import Role
from accounts.permissions import (
    IsStudent,
    IsStaffRole,
    IsRegistrar,
    IsAdminRole,
)


@pytest.fixture
def mock_request():
    request = Mock()
    request.user = Mock()
    request.user.is_authenticated = True
    return request


def test_is_student_permission(mock_request):
    mock_request.user.role = Role.STUDENT
    assert IsStudent().has_permission(mock_request, None) is True

    mock_request.user.role = Role.STAFF
    assert IsStudent().has_permission(mock_request, None) is False


def test_is_staff_role_permission(mock_request):
    mock_request.user.role = Role.STAFF
    assert IsStaffRole().has_permission(mock_request, None) is True

    mock_request.user.role = Role.STUDENT
    assert IsStaffRole().has_permission(mock_request, None) is False


def test_is_registrar_permission(mock_request):
    mock_request.user.role = Role.REGISTRAR
    assert IsRegistrar().has_permission(mock_request, None) is True

    mock_request.user.role = Role.STUDENT
    assert IsRegistrar().has_permission(mock_request, None) is False


def test_is_admin_role_permission(mock_request):
    mock_request.user.role = Role.ADMIN
    assert IsAdminRole().has_permission(mock_request, None) is True

    mock_request.user.role = Role.STUDENT
    assert IsAdminRole().has_permission(mock_request, None) is False


def test_permissions_unauthenticated(mock_request):
    mock_request.user.is_authenticated = False
    mock_request.user.role = Role.STUDENT
    assert IsStudent().has_permission(mock_request, None) is False
