from django.test import TestCase, override_settings
from django.conf import settings
from rest_framework.test import APIClient


class ProductionConfigAndCORSTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_cors_allowed_origin_returns_access_control_headers(self):
        response = self.client.options(
            '/api/schema/',
            HTTP_ORIGIN='http://localhost:3000',
            HTTP_ACCESS_CONTROL_REQUEST_METHOD='GET'
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
            '/api/schema/',
            HTTP_ORIGIN='http://malicious-site.com',
            HTTP_ACCESS_CONTROL_REQUEST_METHOD='GET'
        )
        self.assertNotIn('access-control-allow-origin', response.headers)

    def test_cors_middleware_is_configured(self):
        self.assertIn(
            'corsheaders.middleware.CorsMiddleware',
            settings.MIDDLEWARE
        )
        self.assertIn('corsheaders', settings.INSTALLED_APPS)

    def test_whitenoise_middleware_is_configured(self):
        self.assertIn(
            'whitenoise.middleware.WhiteNoiseMiddleware',
            settings.MIDDLEWARE
        )

    def test_static_root_is_defined(self):
        self.assertIsNotNone(settings.STATIC_ROOT)
        self.assertTrue(str(settings.STATIC_ROOT).endswith('staticfiles'))

    def test_secure_proxy_ssl_header_configured(self):
        self.assertEqual(
            settings.SECURE_PROXY_SSL_HEADER,
            ('HTTP_X_FORWARDED_PROTO', 'https')
        )

    @override_settings(
        CORS_ALLOWED_ORIGINS=['https://credential-app.vercel.app']
    )
    def test_cors_custom_origin_override(self):
        response = self.client.options(
            '/api/schema/',
            HTTP_ORIGIN='https://credential-app.vercel.app',
            HTTP_ACCESS_CONTROL_REQUEST_METHOD='GET'
        )
        self.assertEqual(
            response.headers.get('access-control-allow-origin'),
            'https://credential-app.vercel.app'
        )
