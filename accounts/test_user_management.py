import pytest
from django.urls import reverse
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient
from accounts.models import Role
from audit.models import AuditLog
from accounts.services import AccountService

User = get_user_model()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def admin_user():
    return User.objects.create_user(
        username='admin1',
        email='admin1@test.com',
        password='pass',
        role=Role.ADMIN
    )


@pytest.fixture
def student_user():
    return User.objects.create_user(
        username='student1',
        email='student1@test.com',
        password='pass',
        role=Role.STUDENT
    )


@pytest.mark.django_db
class TestAccountService:
    def test_create_user_audits_and_forces_password_change(self, admin_user):
        user = AccountService.create_user(
            actor=admin_user,
            username='new_staff',
            email='staff@test.com',
            password='secure',
            role=Role.STAFF
        )

        assert user.force_password_change is True

        log = AuditLog.objects.get(action='USER_CREATED')
        assert log.actor == admin_user
        assert log.object_id == str(user.id)
        assert log.new_state['username'] == 'new_staff'

    def test_update_user_audits_changes(self, admin_user, student_user):
        AccountService.update_user(
            actor=admin_user,
            user=student_user,
            validated_data={'email': 'updated@test.com'}
        )

        log = AuditLog.objects.get(action='USER_UPDATED')
        assert log.previous_state['email'] == 'student1@test.com'
        assert log.new_state['email'] == 'updated@test.com'

    def test_deactivate_user_audits_soft_delete(self, admin_user, student_user):
        AccountService.deactivate_user(
            actor=admin_user,
            user=student_user
        )

        assert student_user.is_active is False
        log = AuditLog.objects.get(action='USER_DEACTIVATED')
        assert log.previous_state['is_active'] is True
        assert log.new_state['is_active'] is False


@pytest.mark.django_db
class TestUserViewSet:
    def test_admin_can_create_user(self, api_client, admin_user):
        api_client.force_authenticate(user=admin_user)
        url = reverse('user-list')
        data = {
            'username': 'created_by_api',
            'email': 'api@test.com',
            'password': 'pass',
            'role': Role.STUDENT
        }

        response = api_client.post(url, data, format='json')
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['force_password_change'] is True

        # Verify Audit Log
        assert AuditLog.objects.filter(action='USER_CREATED').exists()

    def test_student_cannot_access_user_api(self, api_client, student_user):
        api_client.force_authenticate(user=student_user)
        url = reverse('user-list')

        response = api_client.get(url)
        assert response.status_code == status.HTTP_403_FORBIDDEN

        response = api_client.post(url, {})
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_delete_performs_soft_delete(self, api_client, admin_user, student_user):
        api_client.force_authenticate(user=admin_user)
        url = reverse('user-detail', kwargs={'pk': student_user.pk})

        response = api_client.delete(url)
        assert response.status_code == status.HTTP_204_NO_CONTENT

        # Record should still exist in DB but be inactive
        student_user.refresh_from_db()
        assert student_user.is_active is False


@pytest.mark.django_db
class TestCurrentUserView:
    def test_current_user_profile(self, api_client, student_user):
        student_user.first_name = "Jane"
        student_user.last_name = "Doe"
        student_user.save()

        api_client.force_authenticate(user=student_user)
        url = reverse('current-user')
        response = api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data['username'] == 'student1'
        assert response.data['full_name'] == 'Jane Doe'

    def test_current_user_patch(self, api_client, student_user):
        api_client.force_authenticate(user=student_user)
        url = reverse('current-user')
        response = api_client.patch(url, {'first_name': 'UpdatedFirst'}, format='json')
        assert response.status_code == status.HTTP_200_OK
        student_user.refresh_from_db()
        assert student_user.first_name == 'UpdatedFirst'

    def test_unauthenticated_cannot_access_me(self, api_client):
        url = reverse('current-user')
        response = api_client.get(url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestStaffDirectoryView:
    def test_staff_and_registrar_can_access_directory(self, api_client):
        staff = User.objects.create_user(
            username='staff_dir1', password='p', role=Role.STAFF
        )
        registrar = User.objects.create_user(
            username='reg_dir1', password='p', role=Role.REGISTRAR
        )
        admin = User.objects.create_user(
            username='admin_dir1', password='p', role=Role.ADMIN
        )
        student = User.objects.create_user(
            username='stud_dir1', password='p', role=Role.STUDENT
        )

        url = reverse('staff-directory')

        # Staff access
        api_client.force_authenticate(user=staff)
        res = api_client.get(url)
        assert res.status_code == status.HTTP_200_OK
        usernames = [u['username'] for u in res.data]
        assert 'staff_dir1' in usernames
        assert 'reg_dir1' in usernames
        assert 'admin_dir1' in usernames
        assert 'stud_dir1' not in usernames

        # Registrar access
        api_client.force_authenticate(user=registrar)
        res = api_client.get(url)
        assert res.status_code == status.HTTP_200_OK

        # Admin access
        api_client.force_authenticate(user=admin)
        res = api_client.get(url)
        assert res.status_code == status.HTTP_200_OK

        # Student forbidden
        api_client.force_authenticate(user=student)
        assert api_client.get(url).status_code == status.HTTP_403_FORBIDDEN

        # Unauthenticated unauthorized
        api_client.force_authenticate(user=None)
        assert api_client.get(url).status_code == status.HTTP_401_UNAUTHORIZED
