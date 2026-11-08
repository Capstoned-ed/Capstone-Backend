from django.test import TestCase, override_settings
from django.conf import settings
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
from unittest.mock import patch
from accounts.models import User, Role


class ProductionConfigAndCORSTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.stable_endpoint = '/api/token/'

    def tearDown(self):
        cache.clear()

    def test_cors_allowed_origin_returns_access_control_headers(self):
        response = self.client.options(
            self.stable_endpoint,
            HTTP_ORIGIN='http://localhost:3000',
            HTTP_ACCESS_CONTROL_REQUEST_METHOD='POST'
        )
        self.assertIn('access-control-allow-origin', response.headers)
        self.assertEqual(
            response.headers['access-control-allow-origin'],
            'http://localhost:3000'
        )
        self.assertEqual(
            response.headers.get('access-control-allow-credentials'),
            'true'
        )

    def test_cors_disallowed_origin_does_not_return_access_control_headers(
        self
    ):
        response = self.client.options(
            self.stable_endpoint,
            HTTP_ORIGIN='http://malicious-site.com',
            HTTP_ACCESS_CONTROL_REQUEST_METHOD='POST'
        )
        self.assertNotIn('access-control-allow-origin', response.headers)

    @override_settings(
        CORS_ALLOWED_ORIGINS=['https://credential-app.vercel.app']
    )
    def test_cors_custom_origin_override(self):
        response = self.client.options(
            self.stable_endpoint,
            HTTP_ORIGIN='https://credential-app.vercel.app',
            HTTP_ACCESS_CONTROL_REQUEST_METHOD='POST'
        )
        self.assertEqual(
            response.headers.get('access-control-allow-origin'),
            'https://credential-app.vercel.app'
        )

    def test_security_middleware_presence(self):
        self.assertIn(
            'django.middleware.security.SecurityMiddleware',
            settings.MIDDLEWARE
        )
        self.assertIn(
            'corsheaders.middleware.CorsMiddleware',
            settings.MIDDLEWARE
        )
        self.assertIn(
            'whitenoise.middleware.WhiteNoiseMiddleware',
            settings.MIDDLEWARE
        )

    def test_static_root_and_storage_configured(self):
        self.assertIsNotNone(settings.STATIC_ROOT)
        self.assertTrue(str(settings.STATIC_ROOT).endswith('staticfiles'))

    @override_settings(DEBUG=False)
    def test_debug_disabled_in_production(self):
        self.assertFalse(settings.DEBUG)

    def test_session_and_csrf_cookie_secure_settings(self):
        self.assertTrue(hasattr(settings, 'SESSION_COOKIE_SECURE'))
        self.assertTrue(hasattr(settings, 'CSRF_COOKIE_SECURE'))

    @override_settings(SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True)
    def test_session_and_csrf_cookie_secure_override(self):
        self.assertTrue(settings.SESSION_COOKIE_SECURE)
        self.assertTrue(settings.CSRF_COOKIE_SECURE)

    def test_secure_content_type_nosniff_header(self):
        self.assertTrue(settings.SECURE_CONTENT_TYPE_NOSNIFF)
        response = self.client.get(self.stable_endpoint)
        self.assertEqual(
            response.headers.get('x-content-type-options'),
            'nosniff'
        )

    def test_x_frame_options_deny(self):
        self.assertEqual(settings.X_FRAME_OPTIONS, 'DENY')
        response = self.client.get(self.stable_endpoint)
        self.assertEqual(
            response.headers.get('x-frame-options'),
            'DENY'
        )

    @override_settings(
        SECURE_HSTS_SECONDS=31536000,
        SECURE_HSTS_INCLUDE_SUBDOMAINS=True,
        SECURE_HSTS_PRELOAD=True
    )
    def test_hsts_configuration_when_enabled(self):
        self.assertEqual(settings.SECURE_HSTS_SECONDS, 31536000)
        self.assertTrue(settings.SECURE_HSTS_INCLUDE_SUBDOMAINS)
        self.assertTrue(settings.SECURE_HSTS_PRELOAD)
        response = self.client.get(
            self.stable_endpoint,
            HTTP_X_FORWARDED_PROTO='https'
        )
        self.assertIn('strict-transport-security', response.headers)

    @override_settings(
        ALLOWED_HOSTS=['allowed-domain.com', 'localhost', '127.0.0.1']
    )
    def test_allowed_hosts_validation(self):
        response = self.client.get(
            self.stable_endpoint,
            HTTP_HOST='disallowed-host.com'
        )
        self.assertEqual(response.status_code, 400)

    def test_trusted_proxy_ssl_header_configuration(self):
        self.assertEqual(
            settings.SECURE_PROXY_SSL_HEADER,
            ('HTTP_X_FORWARDED_PROTO', 'https')
        )
        response = self.client.get(
            self.stable_endpoint,
            HTTP_X_FORWARDED_PROTO='https'
        )
        self.assertTrue(response.wsgi_request.is_secure())

    def test_throttling_classes_and_rates_configured(self):
        drf_settings = settings.REST_FRAMEWORK
        self.assertIn('DEFAULT_THROTTLE_CLASSES', drf_settings)
        throttle_classes = drf_settings['DEFAULT_THROTTLE_CLASSES']
        self.assertIn(
            'rest_framework.throttling.AnonRateThrottle',
            throttle_classes
        )
        self.assertIn(
            'rest_framework.throttling.UserRateThrottle',
            throttle_classes
        )
        self.assertIn('DEFAULT_THROTTLE_RATES', drf_settings)
        rates = drf_settings['DEFAULT_THROTTLE_RATES']
        self.assertIn('anon', rates)
        self.assertIn('user', rates)

    def test_anonymous_rate_throttling_enforced(self):
        with patch.dict(AnonRateThrottle.THROTTLE_RATES, {'anon': '2/min'}):
            res1 = self.client.post('/api/auth/login/', {})
            self.assertEqual(res1.status_code, status.HTTP_400_BAD_REQUEST)
            res2 = self.client.post('/api/auth/login/', {})
            self.assertEqual(res2.status_code, status.HTTP_400_BAD_REQUEST)
            res3 = self.client.post('/api/auth/login/', {})
            self.assertEqual(
                res3.status_code,
                status.HTTP_429_TOO_MANY_REQUESTS
            )

    def test_authenticated_user_rate_throttling_enforced(self):
        user = User.objects.create_user(
            username='throttletest',
            email='throttletest@example.com',
            password='Password123!',
            role=Role.STUDENT
        )
        self.client.force_authenticate(user=user)
        with patch.dict(UserRateThrottle.THROTTLE_RATES, {'user': '2/min'}):
            res1 = self.client.get('/api/credential-types/')
            self.assertEqual(res1.status_code, status.HTTP_200_OK)
            res2 = self.client.get('/api/credential-types/')
            self.assertEqual(res2.status_code, status.HTTP_200_OK)
            res3 = self.client.get('/api/credential-types/')
            self.assertEqual(
                res3.status_code,
                status.HTTP_429_TOO_MANY_REQUESTS
            )
