from rest_framework.test import APITestCase
from django.urls import reverse
from rest_framework import status
from django.contrib.auth import get_user_model
from accounts.models import Role
from .models import CredentialType, CredentialRequest
from audit.models import AuditLog
from decimal import Decimal

User = get_user_model()


class CredentialRequestAPITests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin1', email='a@test.com', password='p', role=Role.ADMIN
        )
        self.registrar = User.objects.create_user(
            username='reg1', email='r@test.com', password='p', role=Role.REGISTRAR
        )
        self.student1 = User.objects.create_user(
            username='stud1', email='s1@test.com', password='p', role=Role.STUDENT
        )
        self.student2 = User.objects.create_user(
            username='stud2', email='s2@test.com', password='p', role=Role.STUDENT
        )
        self.staff = User.objects.create_user(
            username='staff1', email='st@test.com', password='p', role=Role.STAFF
        )

        self.ctype = CredentialType.objects.create(
            code='TOR', name='Transcript', price=Decimal('150.00'), processing_days=5
        )

        self.req1 = CredentialRequest.objects.create(
            user=self.student1, credential_type=self.ctype
        )
        self.req2 = CredentialRequest.objects.create(
            user=self.student2, credential_type=self.ctype
        )

        self.url_list = reverse('credentialrequest-list')
        self.url_detail1 = reverse(
            'credentialrequest-detail', kwargs={'pk': self.req1.pk}
        )
        self.url_detail2 = reverse(
            'credentialrequest-detail', kwargs={'pk': self.req2.pk}
        )

    def test_student_data_isolation_list(self):
        """Student 1 should only see req1, not req2."""
        self.client.force_authenticate(user=self.student1)
        response = self.client.get(self.url_list)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['id'], str(self.req1.id))

    def test_student_direct_object_access_prevention(self):
        """Student 1 trying to access Student 2's request via direct ID returns 404."""
        self.client.force_authenticate(user=self.student1)
        response = self.client.get(self.url_detail2)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_role_based_list_access(self):
        """Staff, Registrar, and Admin should see all requests."""
        for user in [self.staff, self.registrar, self.admin]:
            self.client.force_authenticate(user=user)
            response = self.client.get(self.url_list)
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(len(response.data), 2)

    def test_student_can_create_request_audited(self):
        self.client.force_authenticate(user=self.student1)
        data = {'credential_type': self.ctype.id}
        response = self.client.post(self.url_list, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['user'], self.student1.id)

        # Verify Audit Log
        log = AuditLog.objects.filter(action='REQUEST_CREATED').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.actor, self.student1)
        self.assertEqual(log.new_state['credential_type'], 'TOR')

    def test_role_based_creation_restrictions(self):
        """Staff, Registrar, and Admin cannot create requests."""
        data = {'credential_type': self.ctype.id}
        for user in [self.staff, self.registrar, self.admin]:
            self.client.force_authenticate(user=user)
            response = self.client.post(self.url_list, data, format='json')
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_student_cannot_request_inactive_credential(self):
        """Student receives 400 Bad Request if credential type is inactive."""
        inactive_ctype = CredentialType.objects.create(
            code='INAC', name='Inactive Cert', price=Decimal('10.00'),
            processing_days=1, is_active=False
        )
        self.client.force_authenticate(user=self.student1)
        data = {'credential_type': inactive_ctype.id}
        response = self.client.post(self.url_list, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('credential_type', response.data)

    def test_permission_class_blocks_non_safe_methods(self):
        """
        DELETE/PATCH should be blocked by permission class (403),
        not just ViewSet (405).
        """
        self.client.force_authenticate(user=self.admin)
        response = self.client.delete(self.url_detail1)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        response = self.client.patch(self.url_detail1, {'remarks': 'test'})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
