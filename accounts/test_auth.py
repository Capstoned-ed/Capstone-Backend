import pytest
from django.urls import reverse
from django.contrib.auth import get_user_model
from accounts.models import Role


User = get_user_model()


@pytest.fixture
def api_client():
    from rest_framework.test import APIClient
    return APIClient()


@pytest.fixture
def student_user():
    return User.objects.create_user(
        username='student_auth',
        email='student_auth@test.com',
        password='password123',
        role=Role.STUDENT,
        force_password_change=True
    )


@pytest.mark.django_db
def test_login_returns_custom_claims(api_client, student_user):
    url = reverse('token_obtain_pair')
    data = {
        'username': 'student_auth',
        'password': 'password123'
    }
    response = api_client.post(url, data, format='json')

    assert response.status_code == 200
    assert 'access' in response.data
    assert 'refresh' in response.data

    # Decode access token to check custom claims
    import jwt
    from django.conf import settings

    decoded = jwt.decode(
        response.data['access'],
        settings.SECRET_KEY,
        algorithms=['HS256']
    )

    assert decoded.get('role') == Role.STUDENT
    assert decoded.get('force_password_change') is True


@pytest.mark.django_db
def test_token_refresh(api_client, student_user):
    login_url = reverse('token_obtain_pair')
    login_data = {'username': 'student_auth', 'password': 'password123'}
    login_response = api_client.post(login_url, login_data, format='json')

    refresh_token = login_response.data['refresh']

    refresh_url = reverse('token_refresh')
    refresh_data = {'refresh': refresh_token}
    refresh_response = api_client.post(refresh_url, refresh_data, format='json')

    assert refresh_response.status_code == 200
    assert 'access' in refresh_response.data
    # Since ROTATE_REFRESH_TOKENS is True, we should also get a new refresh token
    assert 'refresh' in refresh_response.data
