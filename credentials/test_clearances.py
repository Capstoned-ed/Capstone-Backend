from django.test import TestCase
from rest_framework.test import APITestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework import status
from rest_framework.exceptions import ValidationError
from django.contrib.auth import get_user_model
from accounts.models import Role
from audit.models import AuditLog
from notifications.models import Notification, NotificationEvent
from credentials.models import (
    ClearanceStatus,
    CredentialType
)
from credentials.services import (
    StudentClearanceService,
    CredentialRequestService
)

User = get_user_model()


class StudentClearanceServiceTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(
            username='stud1', email='s1@test.com', password='p', role=Role.STUDENT
        )
        self.staff = User.objects.create_user(
            username='staff1', email='st@test.com', password='p', role=Role.STAFF
        )

    def test_submit_clearance_success(self):
        file = SimpleUploadedFile(
            "c.pdf", b"%PDF-1.4\n", content_type="application/pdf"
        )
        clearance = StudentClearanceService.submit_clearance(self.student, file)

        self.assertEqual(clearance.status, ClearanceStatus.PENDING)
        self.assertEqual(clearance.user, self.student)

        audit = AuditLog.objects.filter(action='CLEARANCE_SUBMITTED').first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.actor, self.student)

    def test_submit_clearance_resubmission(self):
        file1 = SimpleUploadedFile(
            "c1.pdf", b"%PDF-1.4\n", content_type="application/pdf"
        )
        clearance = StudentClearanceService.submit_clearance(self.student, file1)

        StudentClearanceService.review_clearance(
            self.staff, clearance, ClearanceStatus.REJECTED, "Blurry"
        )
        self.assertEqual(clearance.status, ClearanceStatus.REJECTED)

        file2 = SimpleUploadedFile(
            "c2.pdf", b"%PDF-1.4\n", content_type="application/pdf"
        )
        clearance = StudentClearanceService.submit_clearance(self.student, file2)
        self.assertEqual(clearance.status, ClearanceStatus.PENDING)

    def test_cannot_resubmit_approved_clearance(self):
        file = SimpleUploadedFile(
            "c.pdf", b"%PDF-1.4\n", content_type="application/pdf"
        )
        clearance = StudentClearanceService.submit_clearance(self.student, file)

        StudentClearanceService.review_clearance(
            self.staff, clearance, ClearanceStatus.APPROVED
        )

        with self.assertRaises(ValidationError):
            StudentClearanceService.submit_clearance(self.student, file)

    def test_review_clearance_approved(self):
        file = SimpleUploadedFile(
            "c.pdf", b"%PDF-1.4\n", content_type="application/pdf"
        )
        clearance = StudentClearanceService.submit_clearance(self.student, file)

        updated = StudentClearanceService.review_clearance(
            self.staff, clearance, ClearanceStatus.APPROVED
        )

        self.assertEqual(updated.status, ClearanceStatus.APPROVED)
        self.assertEqual(updated.reviewed_by, self.staff)
        self.assertIsNotNone(updated.reviewed_at)

        self.assertTrue(AuditLog.objects.filter(action='CLEARANCE_APPROVED').exists())
        notif = Notification.objects.filter(
            user=self.student, event_type=NotificationEvent.CLEARANCE_APPROVED
        ).first()
        self.assertIsNotNone(notif)

    def test_rejection_requires_remarks(self):
        file = SimpleUploadedFile(
            "c.pdf", b"%PDF-1.4\n", content_type="application/pdf"
        )
        clearance = StudentClearanceService.submit_clearance(self.student, file)

        with self.assertRaises(ValidationError):
            StudentClearanceService.review_clearance(
                self.staff, clearance, ClearanceStatus.REJECTED, ""
            )

    def test_review_invalid_state(self):
        file = SimpleUploadedFile(
            "c.pdf", b"%PDF-1.4\n", content_type="application/pdf"
        )
        clearance = StudentClearanceService.submit_clearance(self.student, file)
        StudentClearanceService.review_clearance(
            self.staff, clearance, ClearanceStatus.APPROVED
        )

        with self.assertRaises(ValidationError):
            StudentClearanceService.review_clearance(
                self.staff, clearance, ClearanceStatus.REJECTED, "remarks"
            )


class CredentialRequestValidationTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(
            username='stud1', email='s1@test.com', password='p', role=Role.STUDENT
        )
        self.staff = User.objects.create_user(
            username='staff1', email='st@test.com', password='p', role=Role.STAFF
        )
        self.cred_type = CredentialType.objects.create(
            code="TOR", name="Transcript", price=100.0, processing_days=3
        )

    def test_create_request_fails_without_clearance(self):
        with self.assertRaises(ValidationError):
            CredentialRequestService.create_request(
                actor=self.student,
                validated_data={'credential_type': self.cred_type, 'remarks': ''}
            )

    def test_create_request_success_with_pending_clearance(self):
        file = SimpleUploadedFile(
            "c.pdf", b"%PDF-1.4\n", content_type="application/pdf"
        )
        StudentClearanceService.submit_clearance(self.student, file)

        req = CredentialRequestService.create_request(
            actor=self.student,
            validated_data={'credential_type': self.cred_type, 'remarks': ''}
        )
        self.assertIsNotNone(req)

    def test_create_request_fails_with_rejected_clearance(self):
        file = SimpleUploadedFile(
            "c.pdf", b"%PDF-1.4\n", content_type="application/pdf"
        )
        clearance = StudentClearanceService.submit_clearance(self.student, file)
        StudentClearanceService.review_clearance(
            self.staff, clearance, ClearanceStatus.REJECTED, remarks='Blurry image'
        )

        with self.assertRaises(ValidationError):
            CredentialRequestService.create_request(
                actor=self.student,
                validated_data={'credential_type': self.cred_type, 'remarks': ''}
            )

    def test_create_request_success_with_approved_clearance(self):
        file = SimpleUploadedFile(
            "c.pdf", b"%PDF-1.4\n", content_type="application/pdf"
        )
        clearance = StudentClearanceService.submit_clearance(self.student, file)
        StudentClearanceService.review_clearance(
            self.staff, clearance, ClearanceStatus.APPROVED
        )

        req = CredentialRequestService.create_request(
            actor=self.student,
            validated_data={'credential_type': self.cred_type, 'remarks': ''}
        )
        self.assertIsNotNone(req)


class StudentClearanceAPITests(APITestCase):
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
        self.student = User.objects.create_user(
            username='stud1', email='s1@test.com', password='p', role=Role.STUDENT
        )
        self.staff = User.objects.create_user(
            username='staff1', email='st@test.com', password='p', role=Role.STAFF
        )
        self.url_list = reverse('studentclearance-list')

    def test_student_submit_clearance(self):
        self.client.force_authenticate(user=self.student)
        file = SimpleUploadedFile(
            "c.pdf", b"%PDF-1.4\n", content_type="application/pdf"
        )
        response = self.client.post(self.url_list, {'file': file}, format='multipart')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['status'], ClearanceStatus.PENDING)

    def test_staff_review_clearance(self):
        file = SimpleUploadedFile(
            "c.pdf", b"%PDF-1.4\n", content_type="application/pdf"
        )
        clearance = StudentClearanceService.submit_clearance(self.student, file)

        self.client.force_authenticate(user=self.staff)
        url = reverse('studentclearance-review', kwargs={'pk': clearance.id})

        response = self.client.patch(
            url, {'status': ClearanceStatus.APPROVED}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], ClearanceStatus.APPROVED)

    def test_student_cannot_review(self):
        file = SimpleUploadedFile(
            "c.pdf", b"%PDF-1.4\n", content_type="application/pdf"
        )
        clearance = StudentClearanceService.submit_clearance(self.student, file)

        self.client.force_authenticate(user=self.student)
        url = reverse('studentclearance-review', kwargs={'pk': clearance.id})

        response = self.client.patch(url, {'status': ClearanceStatus.APPROVED})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_download_strict_ownership(self):
        other_student = User.objects.create_user(
            username='other', email='o@t.com', password='p', role=Role.STUDENT
        )
        file = SimpleUploadedFile(
            "c.pdf", b"%PDF-1.4\n", content_type="application/pdf"
        )
        clearance = StudentClearanceService.submit_clearance(other_student, file)

        url = reverse('studentclearance-download', kwargs={'pk': clearance.id})

        self.client.force_authenticate(user=self.student)
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

        self.client.force_authenticate(user=self.staff)
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_download_missing_file_returns_404(self):
        file = SimpleUploadedFile(
            "c.pdf", b"%PDF-1.4\n", content_type="application/pdf"
        )
        clearance = StudentClearanceService.submit_clearance(self.student, file)

        # Manually delete the file from storage
        clearance.file.delete(save=False)

        url = reverse('studentclearance-download', kwargs={'pk': clearance.id})

        self.client.force_authenticate(user=self.student)
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_staff_review_clearance_with_verified_status(self):
        file = SimpleUploadedFile(
            "c.pdf", b"%PDF-1.4\n", content_type="application/pdf"
        )
        clearance = StudentClearanceService.submit_clearance(self.student, file)

        self.client.force_authenticate(user=self.staff)
        url = reverse('studentclearance-review', kwargs={'pk': clearance.id})

        response = self.client.patch(
            url, {'status': 'VERIFIED'}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], ClearanceStatus.APPROVED)

    def test_staff_review_clearance_idempotent(self):
        file = SimpleUploadedFile(
            "c.pdf", b"%PDF-1.4\n", content_type="application/pdf"
        )
        clearance = StudentClearanceService.submit_clearance(self.student, file)

        self.client.force_authenticate(user=self.staff)
        url = reverse('studentclearance-review', kwargs={'pk': clearance.id})

        # First review: Approve
        res1 = self.client.patch(url, {'status': 'APPROVED'}, format='json')
        self.assertEqual(res1.status_code, status.HTTP_200_OK)
        self.assertEqual(res1.data['status'], ClearanceStatus.APPROVED)

        # Second review: Idempotent re-approval succeeds without 400
        res2 = self.client.patch(url, {'status': 'APPROVED'}, format='json')
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertEqual(res2.data['status'], ClearanceStatus.APPROVED)

    def test_staff_review_clearance_reject_requires_remarks(self):
        file = SimpleUploadedFile(
            "c.pdf", b"%PDF-1.4\n", content_type="application/pdf"
        )
        clearance = StudentClearanceService.submit_clearance(self.student, file)

        self.client.force_authenticate(user=self.staff)
        url = reverse('studentclearance-review', kwargs={'pk': clearance.id})

        # Reject without remarks causes 400
        res1 = self.client.patch(url, {'status': 'REJECTED'}, format='json')
        self.assertEqual(res1.status_code, status.HTTP_400_BAD_REQUEST)

        # Reject with remarks succeeds
        res2 = self.client.patch(
            url, {'status': 'REJECTED', 'remarks': 'Missing signature.'}, format='json'
        )
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertEqual(res2.data['status'], ClearanceStatus.REJECTED)
        self.assertEqual(res2.data['remarks'], 'Missing signature.')

    def test_credential_request_serializer_clearance_fields(self):
        from credentials.serializers import CredentialRequestSerializer
        file = SimpleUploadedFile(
            "clearance_doc.pdf", b"%PDF-1.4\n", content_type="application/pdf"
        )
        clearance = StudentClearanceService.submit_clearance(self.student, file)
        cred_type = CredentialType.objects.create(
            code="CT1", name="Test Cert", price=100.0, processing_days=3
        )
        req = CredentialRequestService.create_request(
            actor=self.student,
            validated_data={'credential_type': cred_type, 'remarks': 'Need copy'}
        )

        data = CredentialRequestSerializer(req).data
        self.assertEqual(data['clearance_id'], str(clearance.id))
        self.assertEqual(data['clearance_status'], ClearanceStatus.PENDING)
        self.assertTrue(data['clearance_file_name'].endswith('.pdf'))
        self.assertTrue(data['clearance_is_pdf'])

    def test_payment_serializer_currency_sanitization(self):
        from credentials.serializers import PaymentSerializer
        file = SimpleUploadedFile(
            "c.pdf", b"%PDF-1.4\n", content_type="application/pdf"
        )
        StudentClearanceService.submit_clearance(self.student, file)
        cred_type = CredentialType.objects.create(
            code="CT2", name="TOR", price=150.0, processing_days=3
        )
        req = CredentialRequestService.create_request(
            actor=self.student,
            validated_data={'credential_type': cred_type, 'remarks': ''}
        )

        receipt = SimpleUploadedFile(
            "receipt.pdf", b"%PDF-1.4\n", content_type="application/pdf"
        )
        serializer = PaymentSerializer(data={
            'request': req.id,
            'amount': '₱150.00',
            'receipt_image': receipt,
            'receipt_reference_number': 'OR-9988'
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(str(serializer.validated_data['amount']), '150.00')

    def test_registrar_and_staff_transitions(self):
        from credentials.models import RequestStatus
        file = SimpleUploadedFile(
            "c.pdf", b"%PDF-1.4\n", content_type="application/pdf"
        )
        StudentClearanceService.submit_clearance(self.student, file)
        cred_type = CredentialType.objects.create(
            code="CT3", name="HD", price=100.0, processing_days=3
        )
        req = CredentialRequestService.create_request(
            actor=self.student,
            validated_data={'credential_type': cred_type, 'remarks': ''}
        )
        req.status = RequestStatus.PROCESSING
        req.save()

        registrar = User.objects.create_user(
            username='reg1', email='r1@test.com', password='p', role=Role.REGISTRAR
        )

        # Registrar can transition PROCESSING -> READY_FOR_RELEASE
        updated = CredentialRequestService.transition_request(
            actor=registrar,
            credential_request=req,
            new_status=RequestStatus.READY_FOR_RELEASE,
            remarks="Document is printed and signed."
        )
        self.assertEqual(updated.status, RequestStatus.READY_FOR_RELEASE)

        # Staff can transition READY_FOR_RELEASE -> RELEASED
        final_req = CredentialRequestService.transition_request(
            actor=self.staff,
            credential_request=updated,
            new_status=RequestStatus.RELEASED,
            remarks="Claimed by student."
        )
        self.assertEqual(final_req.status, RequestStatus.RELEASED)
