from rest_framework.test import APITestCase
from django.urls import reverse
from rest_framework import status
from django.contrib.auth import get_user_model
from accounts.models import Role
from .models import CredentialType
from audit.models import AuditLog
from decimal import Decimal

User = get_user_model()


class CredentialTypeTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin1', email='a@test.com', password='p', role=Role.ADMIN
        )
        self.registrar = User.objects.create_user(
            username='reg1', email='r@test.com', password='p', role=Role.REGISTRAR
        )
        self.student = User.objects.create_user(
            username='stud1', email='s@test.com', password='p', role=Role.STUDENT
        )
        self.staff = User.objects.create_user(
            username='staff1', email='st@test.com', password='p', role=Role.STAFF
        )

        self.ctype = CredentialType.objects.create(
            code='TOR', name='Transcript', price=Decimal('150.00'), processing_days=5
        )
        self.url_list = reverse('credentialtype-list')
        self.url_detail = reverse('credentialtype-detail', kwargs={'pk': self.ctype.pk})

    def test_student_read_access(self):
        self.client.force_authenticate(user=self.student)
        response = self.client.get(self.url_list)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_inactive_credential_visibility(self):
        # Create an inactive credential type
        CredentialType.objects.create(
            code='INAC', name='Inactive Cert', price=Decimal('10.00'),
            processing_days=1, is_active=False
        )

        # Admin should see both active and inactive (2 total)
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(self.url_list)
        self.assertEqual(len(response.data), 2)

        # Student should only see active (1 total)
        self.client.force_authenticate(user=self.student)
        response = self.client.get(self.url_list)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['code'], 'TOR')

    def test_student_write_forbidden(self):
        self.client.force_authenticate(user=self.student)
        data = {
            'code': 'COE', 'name': 'Cert', 'price': '50.00', 'processing_days': 2
        }
        response = self.client.post(self.url_list, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        response = self.client.delete(self.url_detail)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_create_success_and_audited(self):
        self.client.force_authenticate(user=self.admin)
        data = {
            'code': 'COE',
            'name': 'Certificate of Enrollment',
            'description': 'Proof of enrollment',
            'price': '50.00',
            'processing_days': 2,
            'is_active': True
        }
        response = self.client.post(self.url_list, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(CredentialType.objects.count(), 2)

        log = AuditLog.objects.filter(action='CREDENTIAL_TYPE_CREATED').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.actor, self.admin)
        self.assertEqual(log.new_state['code'], 'COE')

    def test_registrar_update_success_and_audited(self):
        self.client.force_authenticate(user=self.registrar)
        data = {'price': '200.00'}
        response = self.client.patch(self.url_detail, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.ctype.refresh_from_db()
        self.assertEqual(self.ctype.price, Decimal('200.00'))

        log = AuditLog.objects.filter(action='CREDENTIAL_TYPE_UPDATED').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.actor, self.registrar)
        self.assertEqual(log.new_state['price'], '200.00')

    def test_soft_delete(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.delete(self.url_detail)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        self.ctype.refresh_from_db()
        self.assertFalse(self.ctype.is_active)
        # Should still exist physically
        self.assertEqual(CredentialType.objects.count(), 1)

        log = AuditLog.objects.filter(action='CREDENTIAL_TYPE_DEACTIVATED').first()
        self.assertIsNotNone(log)
