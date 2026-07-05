import pytest
from django.contrib.auth import get_user_model
from accounts.models import Role


User = get_user_model()


@pytest.mark.django_db
def test_create_user_with_role():
    user = User.objects.create_user(
        username='student1',
        email='student1@test.com',
        password='testpassword123',
        role=Role.STUDENT
    )
    assert user.username == 'student1'
    assert user.role == Role.STUDENT
    assert user.force_password_change is False
    assert str(user) == 'student1 (Student)'


@pytest.mark.django_db
def test_create_admin_user():
    admin_user = User.objects.create_superuser(
        username='admin1',
        email='admin@test.com',
        password='testpassword123'
    )
    assert admin_user.is_superuser is True
    assert admin_user.is_staff is True
    assert admin_user.role == Role.ADMIN


@pytest.mark.django_db
def test_force_password_change_flag():
    user = User.objects.create_user(
        username='staff1',
        email='staff@test.com',
        password='temp',
        role=Role.STAFF,
        force_password_change=True
    )
    assert user.force_password_change is True
