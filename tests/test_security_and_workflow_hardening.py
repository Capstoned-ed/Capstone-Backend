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
    PaymentStatus,
    RequestStatus,
    RequirementDocument,
    StudentClearance,
)
from credentials.storage import private_storage
from notifications.models import Notification

User = get_user_model()


class SecurityAndWorkflowHardeningTests(APITestCase):
    """
    Hardening, Security, Authorization, Audit, Notification, and Regression
    test suite for the Credential Request System backend.
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

    def get_valid_pdf(self, name="file.pdf"):
        # Real PDF header magic bytes "%PDF-1.4"
        return SimpleUploadedFile(
            name,
            b"%PDF-1.4\n%PDF content stream data for testing",
            content_type="application/pdf",
        )

    def get_valid_png(self, name="file.png"):
        # Real PNG header magic bytes
        png_header = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        return SimpleUploadedFile(
            name,
            png_header,
            content_type="image/png",
        )

    def setUp(self):
        self.student1 = User.objects.create_user(
            username='sec_student1',
            email='sec_s1@test.com',
            password='password123',
            role=Role.STUDENT,
        )
        self.student2 = User.objects.create_user(
            username='sec_student2',
            email='sec_s2@test.com',
            password='password123',
            role=Role.STUDENT,
        )
        self.staff = User.objects.create_user(
            username='sec_staff',
            email='sec_staff@test.com',
            password='password123',
            role=Role.STAFF,
        )
        self.registrar = User.objects.create_user(
            username='sec_reg',
            email='sec_reg@test.com',
            password='password123',
            role=Role.REGISTRAR,
        )
        self.admin = User.objects.create_user(
            username='sec_admin',
            email='sec_admin@test.com',
            password='password123',
            role=Role.ADMIN,
        )

        self.cred_type = CredentialType.objects.create(
            code='TOR_SEC',
            name='Transcript of Records Sec',
            price=Decimal('200.00'),
            processing_days=3,
            is_active=True,
        )

        # Clearances for student1 & student2
        self.clearance1 = StudentClearance.objects.create(
            user=self.student1,
            status=ClearanceStatus.APPROVED,
            file=self.get_valid_pdf("c1.pdf"),
        )
        self.clearance2 = StudentClearance.objects.create(
            user=self.student2,
            status=ClearanceStatus.APPROVED,
            file=self.get_valid_pdf("c2.pdf"),
        )

        # Requests for student1 & student2
        self.req1 = CredentialRequest.objects.create(
            user=self.student1,
            credential_type=self.cred_type,
            status=RequestStatus.PENDING,
        )
        self.req2 = CredentialRequest.objects.create(
            user=self.student2,
            credential_type=self.cred_type,
            status=RequestStatus.PAYMENT_PENDING,
        )

        # Requirement Document & Payment for student1
        self.doc1 = RequirementDocument.objects.create(
            request=self.req1,
            document_type='ID',
            file=self.get_valid_pdf("doc1.pdf"),
        )
        self.payment1 = Payment.objects.create(
            request=self.req2,
            amount=Decimal('200.00'),
            receipt_image=self.get_valid_pdf("rec1.pdf"),
            status=PaymentStatus.PENDING,
        )

    # -------------------------------------------------------------------------
    # 1. Private File Access Security
    # -------------------------------------------------------------------------
    def test_student_cannot_download_other_students_requirement_document(self):
        self.client.force_authenticate(user=self.student2)
        url = reverse(
            'requirementdocument-download', kwargs={'pk': self.doc1.pk}
        )
        resp = self.client.get(url)
        self.assertIn(
            resp.status_code,
            [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND],
        )

    def test_student_cannot_download_other_students_clearance_file(self):
        self.client.force_authenticate(user=self.student2)
        url = reverse(
            'studentclearance-download', kwargs={'pk': self.clearance1.pk}
        )
        resp = self.client.get(url)
        self.assertIn(
            resp.status_code,
            [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND],
        )

    def test_student_cannot_download_other_students_payment_receipt(self):
        self.client.force_authenticate(user=self.student1)
        url = reverse(
            'payment-download', kwargs={'pk': self.payment1.pk}
        )
        resp = self.client.get(url)
        self.assertIn(
            resp.status_code,
            [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND],
        )

    def test_unauthenticated_user_cannot_download_private_files(self):
        self.client.logout()
        doc_url = reverse(
            'requirementdocument-download', kwargs={'pk': self.doc1.pk}
        )
        clearance_url = reverse(
            'studentclearance-download', kwargs={'pk': self.clearance1.pk}
        )
        payment_url = reverse(
            'payment-download', kwargs={'pk': self.payment1.pk}
        )

        for url in [doc_url, clearance_url, payment_url]:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_staff_and_admin_can_access_authorized_private_files(self):
        doc_url = reverse(
            'requirementdocument-download', kwargs={'pk': self.doc1.pk}
        )
        clearance_url = reverse(
            'studentclearance-download', kwargs={'pk': self.clearance1.pk}
        )
        payment_url = reverse(
            'payment-download', kwargs={'pk': self.payment1.pk}
        )

        for role_user in [self.staff, self.admin]:
            self.client.force_authenticate(user=role_user)
            for url in [doc_url, clearance_url, payment_url]:
                resp = self.client.get(url)
                self.assertEqual(resp.status_code, status.HTTP_200_OK)

    # -------------------------------------------------------------------------
    # 2. Workflow State Machine Hardening
    # -------------------------------------------------------------------------
    def test_invalid_state_machine_transitions(self):
        invalid_transitions = [
            (RequestStatus.RELEASED, RequestStatus.PENDING, self.admin),
            (RequestStatus.RELEASED, RequestStatus.PROCESSING, self.registrar),
            (RequestStatus.REJECTED, RequestStatus.PROCESSING, self.registrar),
            (RequestStatus.CANCELLED, RequestStatus.PAYMENT_PENDING, self.staff),
            (
                RequestStatus.PAYMENT_PENDING,
                RequestStatus.READY_FOR_RELEASE,
                self.registrar,
            ),
            (
                RequestStatus.PROCESSING,
                RequestStatus.PAYMENT_VERIFIED,
                self.staff,
            ),
        ]

        for initial_status, target_status, actor in invalid_transitions:
            req = CredentialRequest.objects.create(
                user=self.student1,
                credential_type=self.cred_type,
                status=initial_status,
            )
            self.client.force_authenticate(user=actor)
            url = reverse('credentialrequest-transition', kwargs={'pk': req.id})
            resp = self.client.patch(
                url, {'status': target_status}, format='json'
            )
            self.assertEqual(
                resp.status_code,
                status.HTTP_400_BAD_REQUEST,
                f"Transition from {initial_status} to {target_status} failed",
            )
            req.refresh_from_db()
            self.assertEqual(req.status, initial_status)

    def test_terminal_states_remain_immutable(self):
        terminal_statuses = [
            RequestStatus.RELEASED,
            RequestStatus.REJECTED,
            RequestStatus.CANCELLED,
        ]
        target_statuses = [
            RequestStatus.PENDING,
            RequestStatus.REQUIREMENTS_VERIFICATION,
            RequestStatus.PAYMENT_PENDING,
            RequestStatus.PAYMENT_VERIFIED,
            RequestStatus.PROCESSING,
            RequestStatus.READY_FOR_RELEASE,
        ]

        for term_status in terminal_statuses:
            req = CredentialRequest.objects.create(
                user=self.student1,
                credential_type=self.cred_type,
                status=term_status,
            )
            self.client.force_authenticate(user=self.admin)
            url = reverse('credentialrequest-transition', kwargs={'pk': req.id})
            for target in target_statuses:
                resp = self.client.patch(
                    url, {'status': target, 'remarks': 'Force update'}, format='json'
                )
                self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
            req.refresh_from_db()
            self.assertEqual(req.status, term_status)

    # -------------------------------------------------------------------------
    # 3. Authorization Bypass Testing
    # -------------------------------------------------------------------------
    def test_students_cannot_invoke_staff_transitions(self):
        self.client.force_authenticate(user=self.student1)
        url = reverse('credentialrequest-transition', kwargs={'pk': self.req1.id})
        resp = self.client.patch(
            url, {'status': RequestStatus.REQUIREMENTS_VERIFICATION}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_students_cannot_invoke_registrar_transitions(self):
        req = CredentialRequest.objects.create(
            user=self.student1,
            credential_type=self.cred_type,
            status=RequestStatus.PAYMENT_VERIFIED,
        )
        self.client.force_authenticate(user=self.student1)
        url = reverse('credentialrequest-transition', kwargs={'pk': req.id})
        resp = self.client.patch(
            url, {'status': RequestStatus.PROCESSING}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_cannot_invoke_registrar_only_transitions(self):
        req = CredentialRequest.objects.create(
            user=self.student1,
            credential_type=self.cred_type,
            status=RequestStatus.PROCESSING,
        )
        self.client.force_authenticate(user=self.staff)
        url = reverse('credentialrequest-transition', kwargs={'pk': req.id})
        resp = self.client.patch(
            url, {'status': RequestStatus.READY_FOR_RELEASE}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthorized_requests_return_correct_status_codes(self):
        url = reverse('credentialrequest-transition', kwargs={'pk': self.req1.id})
        self.client.logout()
        resp = self.client.patch(
            url, {'status': RequestStatus.CANCELLED}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    # -------------------------------------------------------------------------
    # 4. Audit Log Integrity
    # -------------------------------------------------------------------------
    def test_failed_transitions_do_not_create_audit_log(self):
        initial_log_count = AuditLog.objects.count()
        self.client.force_authenticate(user=self.student1)
        url = reverse('credentialrequest-transition', kwargs={'pk': self.req1.id})
        resp = self.client.patch(
            url, {'status': RequestStatus.PROCESSING}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(AuditLog.objects.count(), initial_log_count)

    def test_unauthorized_actions_do_not_create_audit_log(self):
        initial_log_count = AuditLog.objects.count()
        self.client.force_authenticate(user=self.student1)
        url = reverse('credentialrequest-transition', kwargs={'pk': self.req1.id})
        resp = self.client.patch(
            url, {'status': RequestStatus.REQUIREMENTS_VERIFICATION}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(AuditLog.objects.count(), initial_log_count)

    def test_failed_payment_verification_attempts_do_not_create_audit_log(self):
        initial_log_count = AuditLog.objects.count()
        self.client.force_authenticate(user=self.staff)
        url = reverse('payment-verify', kwargs={'pk': self.payment1.pk})
        # REJECT requires remarks; omitting remarks causes 400 failure
        resp = self.client.patch(url, {'action': 'REJECT'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(AuditLog.objects.count(), initial_log_count)

    def test_failed_clearance_review_attempts_do_not_create_audit_log(self):
        clear_user = User.objects.create_user(
            username='clear_user',
            email='cu@t.com',
            password='p',
            role=Role.STUDENT,
        )
        clearance = StudentClearance.objects.create(
            user=clear_user,
            status=ClearanceStatus.PENDING,
            file=self.get_valid_pdf("c_pend.pdf"),
        )
        initial_log_count = AuditLog.objects.count()
        self.client.force_authenticate(user=self.staff)
        url = reverse('studentclearance-review', kwargs={'pk': clearance.pk})
        # REJECT requires remarks; omitting remarks causes 400 failure
        resp = self.client.patch(url, {'status': ClearanceStatus.REJECTED})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(AuditLog.objects.count(), initial_log_count)

    # -------------------------------------------------------------------------
    # 5. Notification Integrity
    # -------------------------------------------------------------------------
    def test_notifications_created_only_after_successful_state_transitions(self):
        initial_notif_count = Notification.objects.count()
        self.client.force_authenticate(user=self.staff)
        url = reverse('payment-verify', kwargs={'pk': self.payment1.pk})
        resp = self.client.patch(url, {'action': 'VERIFY'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertGreater(Notification.objects.count(), initial_notif_count)

    def test_invalid_transitions_generate_no_notifications(self):
        initial_notif_count = Notification.objects.count()
        self.client.force_authenticate(user=self.staff)
        url = reverse('credentialrequest-transition', kwargs={'pk': self.req1.id})
        resp = self.client.patch(
            url, {'status': RequestStatus.RELEASED}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Notification.objects.count(), initial_notif_count)

    def test_unauthorized_actions_generate_no_notifications(self):
        initial_notif_count = Notification.objects.count()
        self.client.force_authenticate(user=self.student1)
        url = reverse('credentialrequest-transition', kwargs={'pk': self.req1.id})
        resp = self.client.patch(
            url, {'status': RequestStatus.REQUIREMENTS_VERIFICATION}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(Notification.objects.count(), initial_notif_count)

    def test_failed_payment_verification_generates_no_notification(self):
        initial_notif_count = Notification.objects.count()
        self.client.force_authenticate(user=self.staff)
        url = reverse('payment-verify', kwargs={'pk': self.payment1.pk})
        resp = self.client.patch(
            url, {'action': 'INVALID_ACTION'}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Notification.objects.count(), initial_notif_count)

    def test_failed_clearance_review_generates_no_notification(self):
        clear_user = User.objects.create_user(
            username='clear_user2',
            email='cu2@t.com',
            password='p',
            role=Role.STUDENT,
        )
        clearance = StudentClearance.objects.create(
            user=clear_user,
            status=ClearanceStatus.PENDING,
            file=self.get_valid_pdf("c_pend2.pdf"),
        )
        initial_notif_count = Notification.objects.count()
        self.client.force_authenticate(user=self.staff)
        url = reverse('studentclearance-review', kwargs={'pk': clearance.pk})
        resp = self.client.patch(url, {'status': 'INVALID_STATUS'})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Notification.objects.count(), initial_notif_count)

    # -------------------------------------------------------------------------
    # 6. Queryset Isolation Hardening
    # -------------------------------------------------------------------------
    def test_student_cannot_access_other_student_request_detail(self):
        self.client.force_authenticate(user=self.student1)
        url = reverse('credentialrequest-detail', kwargs={'pk': self.req2.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_student_cannot_access_other_student_documents(self):
        self.client.force_authenticate(user=self.student2)
        url = reverse('requirementdocument-detail', kwargs={'pk': self.doc1.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_student_cannot_access_other_student_payments(self):
        self.client.force_authenticate(user=self.student1)
        url = reverse('payment-detail', kwargs={'pk': self.payment1.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_student_cannot_access_other_student_clearance(self):
        self.client.force_authenticate(user=self.student1)
        url = reverse(
            'studentclearance-detail', kwargs={'pk': self.clearance2.pk}
        )
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_list_endpoints_never_leak_records_belonging_to_other_students(self):
        self.client.force_authenticate(user=self.student1)

        req_resp = self.client.get(reverse('credentialrequest-list'))
        req_items = (
            req_resp.data
            if isinstance(req_resp.data, list)
            else req_resp.data.get('results', [])
        )
        req_ids = [r['id'] for r in req_items]
        self.assertIn(str(self.req1.id), req_ids)
        self.assertNotIn(str(self.req2.id), req_ids)

        doc_resp = self.client.get(reverse('requirementdocument-list'))
        doc_items = (
            doc_resp.data
            if isinstance(doc_resp.data, list)
            else doc_resp.data.get('results', [])
        )
        doc_ids = [d['id'] for d in doc_items]
        self.assertIn(str(self.doc1.id), doc_ids)

        pay_resp = self.client.get(reverse('payment-list'))
        pay_items = (
            pay_resp.data
            if isinstance(pay_resp.data, list)
            else pay_resp.data.get('results', [])
        )
        pay_ids = [p['id'] for p in pay_items]
        self.assertNotIn(str(self.payment1.id), pay_ids)

        clear_resp = self.client.get(reverse('studentclearance-list'))
        clear_items = (
            clear_resp.data
            if isinstance(clear_resp.data, list)
            else clear_resp.data.get('results', [])
        )
        clear_ids = [c['id'] for c in clear_items]
        self.assertIn(str(self.clearance1.id), clear_ids)
        self.assertNotIn(str(self.clearance2.id), clear_ids)

    # -------------------------------------------------------------------------
    # 7. File Validation Security
    # -------------------------------------------------------------------------
    def test_disallowed_extensions_are_rejected(self):
        self.client.force_authenticate(user=self.student1)
        bad_file = SimpleUploadedFile(
            "exploit.exe",
            b"%PDF-1.4\nMalicious code",
            content_type="application/x-msdownload",
        )
        url = reverse('studentclearance-list')
        resp = self.client.post(url, {'file': bad_file}, format='multipart')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_oversized_files_are_rejected(self):
        self.client.force_authenticate(user=self.student1)
        # 6MB byte payload (exceeding 5MB limit)
        oversized = SimpleUploadedFile(
            "large.pdf",
            b"%PDF-1.4\n" + b"X" * (6 * 1024 * 1024),
            content_type="application/pdf",
        )
        url = reverse('studentclearance-list')
        resp = self.client.post(url, {'file': oversized}, format='multipart')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_mime_type_spoofing_attempts_are_rejected(self):
        self.client.force_authenticate(user=self.student1)
        # File named .pdf but containing plain text magic bytes
        spoofed_file = SimpleUploadedFile(
            "fake.pdf",
            b"PLAIN TEXT MALICIOUS CONTENT NOT A REAL PDF",
            content_type="application/pdf",
        )
        url = reverse('studentclearance-list')
        resp = self.client.post(url, {'file': spoofed_file}, format='multipart')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    # -------------------------------------------------------------------------
    # 8. Regression Protection
    # -------------------------------------------------------------------------
    def test_clearance_prerequisite_enforcement(self):
        new_student = User.objects.create_user(
            username='no_clearance_stud',
            email='noclear@test.com',
            password='password123',
            role=Role.STUDENT,
        )
        self.client.force_authenticate(user=new_student)
        url = reverse('credentialrequest-list')
        resp = self.client.post(
            url, {'credential_type': self.cred_type.id}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_payment_verification_prerequisite(self):
        req = CredentialRequest.objects.create(
            user=self.student1,
            credential_type=self.cred_type,
            status=RequestStatus.PAYMENT_PENDING,
        )
        # Registrar attempts to bypass payment verification -> Fails
        self.client.force_authenticate(user=self.registrar)
        url = reverse('credentialrequest-transition', kwargs={'pk': req.id})
        resp = self.client.patch(
            url, {'status': RequestStatus.PROCESSING}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_role_based_transition_restrictions(self):
        req = CredentialRequest.objects.create(
            user=self.student1,
            credential_type=self.cred_type,
            status=RequestStatus.REQUIREMENTS_VERIFICATION,
        )
        # Student cannot perform staff transition to PAYMENT_PENDING
        self.client.force_authenticate(user=self.student1)
        url = reverse('credentialrequest-transition', kwargs={'pk': req.id})
        resp = self.client.patch(
            url, {'status': RequestStatus.PAYMENT_PENDING}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_ownership_checks(self):
        self.client.force_authenticate(user=self.student1)
        # Student 1 attempts to upload document to Student 2's request
        url = reverse('requirementdocument-list')
        resp = self.client.post(
            url,
            {
                'request': str(self.req2.id),
                'document_type': 'ID',
                'file': self.get_valid_pdf("doc.pdf"),
            },
            format='multipart',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_private_file_protection(self):
        self.client.logout()
        url = reverse(
            'studentclearance-download', kwargs={'pk': self.clearance1.pk}
        )
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
