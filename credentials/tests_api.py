from rest_framework.test import APITestCase
from django.urls import reverse
from rest_framework import status
from django.contrib.auth import get_user_model
from accounts.models import Role
from .models import CredentialType, CredentialRequest, StudentClearance, ClearanceStatus
from audit.models import AuditLog
from decimal import Decimal
from django.core.files.uploadedfile import SimpleUploadedFile

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

        StudentClearance.objects.create(
            user=self.student1,
            status=ClearanceStatus.APPROVED,
            file=SimpleUploadedFile("dummy.pdf", b"content",
                                    content_type="application/pdf")
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

        response = self.client.put(self.url_detail1, {'remarks': 'test'})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_transition_endpoint_success(self):
        """Staff can transition PENDING to REQUIREMENTS_VERIFICATION."""
        self.client.force_authenticate(user=self.staff)
        url = reverse('credentialrequest-transition', kwargs={'pk': self.req1.pk})
        response = self.client.patch(
            url, {'status': 'REQUIREMENTS_VERIFICATION'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.req1.refresh_from_db()
        self.assertEqual(self.req1.status, 'REQUIREMENTS_VERIFICATION')

    def test_transition_endpoint_student_cancel(self):
        """Student can cancel their own PENDING request."""
        self.client.force_authenticate(user=self.student1)
        url = reverse('credentialrequest-transition', kwargs={'pk': self.req1.pk})
        response = self.client.patch(url, {'status': 'CANCELLED'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.req1.refresh_from_db()
        self.assertEqual(self.req1.status, 'CANCELLED')

    def test_transition_endpoint_unauthorized_role(self):
        """Student cannot transition PENDING to REQUIREMENTS_VERIFICATION."""
        self.client.force_authenticate(user=self.student1)
        url = reverse('credentialrequest-transition', kwargs={'pk': self.req1.pk})
        response = self.client.patch(
            url, {'status': 'REQUIREMENTS_VERIFICATION'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn('permission', str(response.data).lower())

    def test_transition_requires_remarks_for_rejection(self):
        """Staff rejecting a request without remarks should fail."""
        self.req1.status = 'REQUIREMENTS_VERIFICATION'
        self.req1.save()
        self.client.force_authenticate(user=self.staff)
        url = reverse('credentialrequest-transition', kwargs={'pk': self.req1.pk})
        response = self.client.patch(url, {'status': 'REJECTED'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('remarks', response.data[0].lower())


class RequirementDocumentAPITests(APITestCase):
    @classmethod
    def setUpClass(cls):
        import tempfile
        super().setUpClass()
        cls.temp_media_dir = tempfile.mkdtemp()
        from credentials.storage import private_storage
        cls.original_private_location = private_storage.location
        private_storage.location = cls.temp_media_dir

    @classmethod
    def tearDownClass(cls):
        import shutil
        from credentials.storage import private_storage
        private_storage.location = cls.original_private_location
        shutil.rmtree(cls.temp_media_dir, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.student1 = User.objects.create_user(
            username='stud1', email='s1@test.com', password='p', role=Role.STUDENT
        )
        self.student2 = User.objects.create_user(
            username='stud2', email='s2@test.com', password='p', role=Role.STUDENT
        )
        self.admin = User.objects.create_user(
            username='admin1', email='a@test.com', password='p', role=Role.ADMIN
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

        self.url_list = reverse('requirementdocument-list')

    def test_student_can_upload_valid_document(self):
        self.client.force_authenticate(user=self.student1)
        file_content = b"%PDF-1.4\n%fake pdf content"
        file = SimpleUploadedFile(
            "test.pdf", file_content, content_type="application/pdf"
        )

        data = {
            'request': self.req1.id,
            'document_type': 'ID',
            'file': file
        }
        response = self.client.post(self.url_list, data, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify Audit Log
        log = AuditLog.objects.filter(action='DOCUMENT_UPLOADED').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.actor, self.student1)
        self.assertEqual(log.new_state['document_type'], 'ID')

    def test_student_cannot_upload_to_others_request(self):
        self.client.force_authenticate(user=self.student1)
        file = SimpleUploadedFile(
            "test.pdf", b"%PDF-1.4\n%fake", content_type="application/pdf"
        )

        data = {
            'request': self.req2.id,  # student2's request
            'document_type': 'ID',
            'file': file
        }
        response = self.client.post(self.url_list, data, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('request', response.data)

    def test_forbidden_file_extension(self):
        self.client.force_authenticate(user=self.student1)
        file = SimpleUploadedFile(
            "test.exe", b"%PDF-1.4\n%fake", content_type="application/pdf"
        )

        data = {
            'request': self.req1.id,
            'document_type': 'ID',
            'file': file
        }
        response = self.client.post(self.url_list, data, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('file', response.data)

    def test_forbidden_mime_type(self):
        self.client.force_authenticate(user=self.student1)
        # Fake an executable inside a PDF extension
        file = SimpleUploadedFile(
            "test.pdf", b"MZ\x90\x00\x03\x00", content_type="application/pdf"
        )

        data = {
            'request': self.req1.id,
            'document_type': 'ID',
            'file': file
        }
        response = self.client.post(self.url_list, data, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('file', response.data)

    def test_oversized_file(self):
        self.client.force_authenticate(user=self.student1)
        # 6MB file
        file = SimpleUploadedFile(
            "test.pdf",
            b"%PDF-1.4\n" + b"x" * (6 * 1024 * 1024),
            content_type="application/pdf"
        )

        data = {
            'request': self.req1.id,
            'document_type': 'ID',
            'file': file
        }
        response = self.client.post(self.url_list, data, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('file', response.data)

    def test_protected_download(self):
        # Upload a document first
        self.client.force_authenticate(user=self.student1)
        file_content = b"%PDF-1.4\n%content"
        file = SimpleUploadedFile(
            "test.pdf", file_content, content_type="application/pdf"
        )
        data = {'request': self.req1.id, 'document_type': 'ID', 'file': file}
        res = self.client.post(self.url_list, data, format='multipart')
        doc_id = res.data['id']

        download_url = reverse(
            'requirementdocument-download', kwargs={'pk': doc_id}
        )

        # Student1 can download
        dl_res = self.client.get(download_url)
        self.assertEqual(dl_res.status_code, status.HTTP_200_OK)
        self.assertEqual(b"".join(dl_res.streaming_content), file_content)

        # Student2 cannot download (due to queryset/object permissions)
        self.client.force_authenticate(user=self.student2)
        dl_res2 = self.client.get(download_url)
        self.assertEqual(dl_res2.status_code, status.HTTP_404_NOT_FOUND)

        # Admin can download
        self.client.force_authenticate(user=self.admin)
        dl_res3 = self.client.get(download_url)
        self.assertEqual(dl_res3.status_code, status.HTTP_200_OK)

    def test_storage_path_verification(self):
        import os
        self.client.force_authenticate(user=self.student1)
        file_content = b"%PDF-1.4\n%content"
        file = SimpleUploadedFile(
            "test.pdf", file_content, content_type="application/pdf"
        )
        data = {'request': self.req1.id, 'document_type': 'ID', 'file': file}
        res = self.client.post(self.url_list, data, format='multipart')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        doc_id = res.data['id']
        from .models import RequirementDocument
        from credentials.storage import private_storage
        doc = RequirementDocument.objects.get(id=doc_id)

        # Verify it uses the private storage
        self.assertTrue(doc.file.path.startswith(str(private_storage.location)))
        self.assertTrue(os.path.exists(doc.file.path))
