import shutil
import tempfile
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Role
from audit.models import AuditLog
from credentials.models import (
    ClearanceStatus,
    CredentialRequest,
    CredentialType,
    Payment,
    StudentClearance,
)
from credentials.storage import private_storage
from notifications.models import Notification, NotificationEvent

User = get_user_model()


class EndToEndWorkflowAPITests(APITestCase):
    """
    Comprehensive End-to-End integration tests for the Credential Request System.

    Validates multi-role business workflows, formal state machine transitions,
    clearance prerequisites, payment verification, audit trail immutability,
    notifications, and object-level security.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.temp_media_dir = tempfile.mkdtemp()
        cls.original_private_location = private_storage.location
        private_storage.location = cls.temp_media_dir

    @classmethod
    def tearDownClass(cls):
        private_storage.location = cls.original_private_location
        shutil.rmtree(cls.temp_media_dir, ignore_errors=True)
        super().tearDownClass()

    def get_dummy_pdf(self, name="clearance.pdf"):
        return SimpleUploadedFile(
            name,
            b"%PDF-1.4\n%Clearance Content",
            content_type="application/pdf",
        )

    def get_dummy_id(self):
        return SimpleUploadedFile(
            "student_id.pdf",
            b"%PDF-1.4\n%Student ID Content",
            content_type="application/pdf",
        )

    def get_dummy_receipt(self, name="receipt.pdf"):
        return SimpleUploadedFile(
            name,
            b"%PDF-1.4\n%Payment Receipt Content",
            content_type="application/pdf",
        )

    def setUp(self):
        # Create users for all distinct system roles
        self.student1 = User.objects.create_user(
            username='e2e_student1',
            email='student1@test.com',
            password='password123',
            role=Role.STUDENT,
        )
        self.student2 = User.objects.create_user(
            username='e2e_student2',
            email='student2@test.com',
            password='password123',
            role=Role.STUDENT,
        )
        self.staff = User.objects.create_user(
            username='e2e_staff',
            email='staff@test.com',
            password='password123',
            role=Role.STAFF,
        )
        self.registrar = User.objects.create_user(
            username='e2e_registrar',
            email='registrar@test.com',
            password='password123',
            role=Role.REGISTRAR,
        )
        self.admin = User.objects.create_user(
            username='e2e_admin',
            email='admin@test.com',
            password='password123',
            role=Role.ADMIN,
        )

        # Create active Credential Type
        self.cred_type = CredentialType.objects.create(
            code='TOR_E2E',
            name='Transcript of Records',
            price=Decimal('150.00'),
            processing_days=3,
            is_active=True,
        )

    def test_complete_happy_path_workflow(self):
        """
        Tests the full lifecycle of a credential request from clearance
        submission to document release, verifying audit logs and notifications.
        """
        # Step 1: Student 1 submits Clearance
        self.client.force_authenticate(user=self.student1)
        clearance_url = reverse('studentclearance-list')
        resp = self.client.post(
            clearance_url, {'file': self.get_dummy_pdf()}, format='multipart'
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        clearance_id = resp.data['id']
        self.assertEqual(resp.data['status'], ClearanceStatus.PENDING)

        # Step 2: Staff reviews & approves Clearance
        self.client.force_authenticate(user=self.staff)
        review_url = reverse(
            'studentclearance-review', kwargs={'pk': clearance_id}
        )
        resp = self.client.patch(
            review_url, {'status': ClearanceStatus.APPROVED}
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(resp.data['status'], ClearanceStatus.APPROVED)

        # Step 3: Student 1 creates Credential Request
        self.client.force_authenticate(user=self.student1)
        request_list_url = reverse('credentialrequest-list')
        resp = self.client.post(
            request_list_url,
            {'credential_type': self.cred_type.id, 'remarks': 'Urgent requirement'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        req_id = resp.data['id']
        self.assertEqual(resp.data['status'], 'PENDING')

        # Step 4: Student 1 uploads Requirement Document (ID)
        doc_list_url = reverse('requirementdocument-list')
        resp = self.client.post(
            doc_list_url,
            {
                'request': req_id,
                'document_type': 'ID',
                'file': self.get_dummy_id(),
            },
            format='multipart',
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)

        # Step 5: Staff transitions Request to REQUIREMENTS_VERIFICATION
        self.client.force_authenticate(user=self.staff)
        transition_url = reverse(
            'credentialrequest-transition', kwargs={'pk': req_id}
        )
        resp = self.client.patch(
            transition_url, {'status': 'REQUIREMENTS_VERIFICATION'}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)

        # Step 6: Staff verifies requirements -> PAYMENT_PENDING
        resp = self.client.patch(
            transition_url, {'status': 'PAYMENT_PENDING'}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)

        # Step 7: Student 1 submits OTC Cashier Payment
        self.client.force_authenticate(user=self.student1)
        payment_list_url = reverse('payment-list')
        resp = self.client.post(
            payment_list_url,
            {
                'request': req_id,
                'amount': '150.00',
                'receipt_reference_number': 'OTC-2026-001',
                'receipt_image': self.get_dummy_receipt(),
            },
            format='multipart',
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        payment_id = resp.data['id']
        self.assertEqual(resp.data['status'], 'PENDING')

        # Step 8: Staff verifies Payment -> Request transitions to PAYMENT_VERIFIED
        self.client.force_authenticate(user=self.staff)
        verify_url = reverse('payment-verify', kwargs={'pk': payment_id})
        resp = self.client.patch(
            verify_url, {'action': 'VERIFY'}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(resp.data['status'], 'VERIFIED')

        req = CredentialRequest.objects.get(id=req_id)
        self.assertEqual(req.status, 'PAYMENT_VERIFIED')

        # Step 9: Registrar transitions PAYMENT_VERIFIED -> PROCESSING
        self.client.force_authenticate(user=self.registrar)
        resp = self.client.patch(
            transition_url, {'status': 'PROCESSING'}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)

        # Step 10: Registrar transitions PROCESSING -> READY_FOR_RELEASE
        resp = self.client.patch(
            transition_url, {'status': 'READY_FOR_RELEASE'}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)

        # Step 11: Staff / Registrar transitions READY_FOR_RELEASE -> RELEASED
        self.client.force_authenticate(user=self.staff)
        resp = self.client.patch(
            transition_url, {'status': 'RELEASED'}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)

        req.refresh_from_db()
        self.assertEqual(req.status, 'RELEASED')

        # Step 12: Verify Audit Logs
        actions = list(
            AuditLog.objects.filter(actor=self.student1).values_list(
                'action', flat=True
            )
        )
        self.assertIn('CLEARANCE_SUBMITTED', actions)
        self.assertIn('REQUEST_CREATED', actions)
        self.assertIn('DOCUMENT_UPLOADED', actions)
        self.assertIn('PAYMENT_SUBMITTED', actions)

        staff_actions = list(
            AuditLog.objects.filter(actor=self.staff).values_list(
                'action', flat=True
            )
        )
        self.assertIn('CLEARANCE_APPROVED', staff_actions)
        self.assertTrue(
            any(a.startswith('REQUEST_STATUS_CHANGED_') for a in staff_actions)
        )
        self.assertIn('PAYMENT_VERIFICATION_VERIFY', staff_actions)

        # Step 13: Verify Notifications for Student 1
        notifs = list(
            Notification.objects.filter(user=self.student1).values_list(
                'event_type', flat=True
            )
        )
        self.assertIn(NotificationEvent.CLEARANCE_APPROVED, notifs)

    def test_clearance_prerequisite_enforcement_and_resubmission(self):
        """
        Verifies that students cannot create requests without approved clearance,
        and tests the clearance rejection & re-upload flow.
        """
        self.client.force_authenticate(user=self.student2)
        request_list_url = reverse('credentialrequest-list')

        # Attempt 1: Request creation with no clearance record -> Fails (400)
        resp = self.client.post(
            request_list_url, {'credential_type': self.cred_type.id}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.data)
        self.assertIn('clearance', str(resp.data).lower())

        # Submit Clearance
        clearance_url = reverse('studentclearance-list')
        resp = self.client.post(
            clearance_url, {'file': self.get_dummy_pdf()}, format='multipart'
        )
        clearance_id = resp.data['id']

        # Attempt 2: Request creation with PENDING clearance -> Fails (400)
        resp = self.client.post(
            request_list_url, {'credential_type': self.cred_type.id}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.data)

        # Staff rejects clearance
        self.client.force_authenticate(user=self.staff)
        review_url = reverse(
            'studentclearance-review', kwargs={'pk': clearance_id}
        )
        resp = self.client.patch(
            review_url,
            {'status': ClearanceStatus.REJECTED, 'remarks': 'Illegible upload'},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)

        # Attempt 3: Request creation with REJECTED clearance -> Fails (400)
        self.client.force_authenticate(user=self.student2)
        resp = self.client.post(
            request_list_url, {'credential_type': self.cred_type.id}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.data)

        # Student re-uploads clearance (fresh file)
        resp = self.client.post(
            clearance_url,
            {'file': self.get_dummy_pdf('clearance2.pdf')},
            format='multipart',
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        new_clearance_id = resp.data['id']

        # Staff approves new clearance
        self.client.force_authenticate(user=self.staff)
        new_review_url = reverse(
            'studentclearance-review', kwargs={'pk': new_clearance_id}
        )
        resp = self.client.patch(
            new_review_url, {'status': ClearanceStatus.APPROVED}
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)

        # Attempt 4: Request creation with APPROVED clearance -> Succeeds!
        self.client.force_authenticate(user=self.student2)
        resp = self.client.post(
            request_list_url, {'credential_type': self.cred_type.id}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)

    def test_requirements_rejection_and_resubmission_flow(self):
        """
        Verifies rejection of requirement documents by staff and mandatory remarks.
        """
        # Setup approved clearance for Student 1
        StudentClearance.objects.create(
            user=self.student1,
            status=ClearanceStatus.APPROVED,
            file=self.get_dummy_pdf(),
        )

        req = CredentialRequest.objects.create(
            user=self.student1,
            credential_type=self.cred_type,
            status='REQUIREMENTS_VERIFICATION',
        )

        # Staff attempts to reject without remarks -> Fails (400)
        self.client.force_authenticate(user=self.staff)
        transition_url = reverse(
            'credentialrequest-transition', kwargs={'pk': req.id}
        )
        resp = self.client.patch(
            transition_url, {'status': 'REQUIREMENTS_REJECTED'}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.data)

        # Staff rejects with mandatory remarks -> Succeeds
        resp = self.client.patch(
            transition_url,
            {
                'status': 'REQUIREMENTS_REJECTED',
                'remarks': 'Missing NSO Birth Certificate',
            },
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        req.refresh_from_db()
        self.assertEqual(req.status, 'REQUIREMENTS_REJECTED')
        self.assertEqual(req.remarks, 'Missing NSO Birth Certificate')

        # Student re-uploads document / resubmits -> Transitions back to PENDING
        self.client.force_authenticate(user=self.student1)
        resp = self.client.patch(
            transition_url, {'status': 'PENDING'}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        req.refresh_from_db()
        self.assertEqual(req.status, 'PENDING')

    def test_payment_rejection_and_retry_flow(self):
        """
        Verifies that rejected payment attempts allow students to submit a new receipt
        while keeping the request in PAYMENT_PENDING.
        """
        req = CredentialRequest.objects.create(
            user=self.student1,
            credential_type=self.cred_type,
            status='PAYMENT_PENDING',
        )

        # Student submits initial payment receipt
        payment1 = Payment.objects.create(
            request=req,
            amount=Decimal('150.00'),
            receipt_reference_number='REF-001',
            receipt_image=self.get_dummy_receipt('receipt1.pdf'),
            status='PENDING',
        )

        # Staff rejects payment due to blurry image
        self.client.force_authenticate(user=self.staff)
        verify_url = reverse('payment-verify', kwargs={'pk': payment1.id})
        resp = self.client.patch(
            verify_url,
            {'action': 'REJECT', 'remarks': 'Receipt image blurry'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        payment1.refresh_from_db()
        self.assertEqual(payment1.status, 'REJECTED')

        # Request remains in PAYMENT_PENDING
        req.refresh_from_db()
        self.assertEqual(req.status, 'PAYMENT_PENDING')

        # Student submits corrected receipt attempt (fresh file)
        self.client.force_authenticate(user=self.student1)
        payment_list_url = reverse('payment-list')
        resp = self.client.post(
            payment_list_url,
            {
                'request': str(req.id),
                'amount': '150.00',
                'receipt_reference_number': 'REF-002',
                'receipt_image': self.get_dummy_receipt('receipt2.pdf'),
            },
            format='multipart',
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        payment2_id = resp.data['id']

        # Staff verifies payment attempt #2
        self.client.force_authenticate(user=self.staff)
        verify_url2 = reverse('payment-verify', kwargs={'pk': payment2_id})
        resp = self.client.patch(
            verify_url2, {'action': 'VERIFY'}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)

        req.refresh_from_db()
        self.assertEqual(req.status, 'PAYMENT_VERIFIED')

    def test_student_cancellation_rules(self):
        """
        Verifies cancellation permissions: students can cancel when PENDING,
        but cannot cancel once payment is verified.
        """
        StudentClearance.objects.create(
            user=self.student1,
            status=ClearanceStatus.APPROVED,
            file=self.get_dummy_pdf(),
        )

        req = CredentialRequest.objects.create(
            user=self.student1,
            credential_type=self.cred_type,
            status='PENDING',
        )

        # Student cancels PENDING request -> Succeeds
        self.client.force_authenticate(user=self.student1)
        transition_url = reverse(
            'credentialrequest-transition', kwargs={'pk': req.id}
        )
        resp = self.client.patch(
            transition_url, {'status': 'CANCELLED'}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        req.refresh_from_db()
        self.assertEqual(req.status, 'CANCELLED')

        # Request in PAYMENT_VERIFIED state
        req2 = CredentialRequest.objects.create(
            user=self.student1,
            credential_type=self.cred_type,
            status='PAYMENT_VERIFIED',
        )
        transition_url2 = reverse(
            'credentialrequest-transition', kwargs={'pk': req2.id}
        )

        # Student attempts to cancel PAYMENT_VERIFIED request -> Fails (403/400)
        resp = self.client.patch(
            transition_url2, {'status': 'CANCELLED'}, format='json'
        )
        self.assertIn(
            resp.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_400_BAD_REQUEST]
        )
        req2.refresh_from_db()
        self.assertNotEqual(req2.status, 'CANCELLED')

    def test_multi_role_rbac_and_data_isolation(self):
        """
        Verifies object-level permissions and role restriction boundaries.
        """
        req_student1 = CredentialRequest.objects.create(
            user=self.student1,
            credential_type=self.cred_type,
            status='PENDING',
        )

        # Student 2 cannot access Student 1's request detail
        self.client.force_authenticate(user=self.student2)
        detail_url = reverse(
            'credentialrequest-detail', kwargs={'pk': req_student1.id}
        )
        resp = self.client.get(detail_url)
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND, resp.data)

        # Student 1 cannot transition request to REQUIREMENTS_VERIFICATION
        # (Staff/Admin only)
        self.client.force_authenticate(user=self.student1)
        transition_url = reverse(
            'credentialrequest-transition', kwargs={'pk': req_student1.id}
        )
        resp = self.client.patch(
            transition_url, {'status': 'REQUIREMENTS_VERIFICATION'}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN, resp.data)

        # Unauthenticated request to transition endpoint -> 401 Unauthorized
        self.client.logout()
        resp = self.client.patch(
            transition_url, {'status': 'CANCELLED'}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED, resp.data)

    def test_registrar_rejection_during_processing(self):
        """
        Verifies Registrar can reject a request during PROCESSING
        with mandatory remarks.
        """
        req = CredentialRequest.objects.create(
            user=self.student1,
            credential_type=self.cred_type,
            status='PROCESSING',
        )

        # Registrar attempts rejection without remarks -> Fails (400)
        self.client.force_authenticate(user=self.registrar)
        transition_url = reverse(
            'credentialrequest-transition', kwargs={'pk': req.id}
        )
        resp = self.client.patch(
            transition_url, {'status': 'REJECTED'}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.data)

        # Registrar rejects with remarks -> Succeeds
        resp = self.client.patch(
            transition_url,
            {'status': 'REJECTED', 'remarks': 'Academic record discrepancy'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        req.refresh_from_db()
        self.assertEqual(req.status, 'REJECTED')
        self.assertEqual(req.remarks, 'Academic record discrepancy')
