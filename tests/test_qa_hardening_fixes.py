import shutil
import tempfile
import time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APITestCase

from accounts.models import Role
from accounts.services import AccountService
from audit.models import AuditLog
from credentials.models import (
    ClearanceStatus,
    CredentialRequest,
    CredentialType,
    RequestStatus,
    StudentClearance,
)
from credentials.services import (
    CredentialRequestService,
    PaymentService,
    StudentClearanceService,
)
from credentials.storage import private_storage
from notifications.models import Notification, NotificationEvent
from notifications.services import NotificationService

User = get_user_model()


class QAHardeningFixesTests(APITestCase):
    """
    Unit and integration tests for QA bug fixes, UX enhancements,
    and role-change hardening edge cases.
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

    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin_qa',
            password='password123',
            email='admin_qa@test.com',
            role=Role.ADMIN
        )
        self.registrar = User.objects.create_user(
            username='registrar_qa',
            password='password123',
            email='registrar_qa@test.com',
            role=Role.REGISTRAR
        )
        self.staff1 = User.objects.create_user(
            username='staff1_qa',
            password='password123',
            email='staff1_qa@test.com',
            role=Role.STAFF
        )
        self.staff2 = User.objects.create_user(
            username='staff2_qa',
            password='password123',
            email='staff2_qa@test.com',
            role=Role.STAFF
        )
        self.student = User.objects.create_user(
            username='student_qa',
            password='password123',
            email='student_qa@test.com',
            role=Role.STUDENT,
            course_code='BSIT'
        )
        self.student2 = User.objects.create_user(
            username='student2_qa',
            password='password123',
            email='student2_qa@test.com',
            role=Role.STUDENT,
            course_code='BSIT'
        )

        self.cred_type = CredentialType.objects.create(
            code='TOR',
            doc_code='1',
            name='Transcript of Records',
            price=Decimal('150.00'),
            processing_days=3,
            is_active=True
        )

        # Upload dummy clearance for student
        dummy_clearance_file = SimpleUploadedFile(
            "clearance.pdf",
            b"%PDF-1.4\nClearance content",
            content_type="application/pdf"
        )
        self.clearance = StudentClearance.objects.create(
            user=self.student,
            file=dummy_clearance_file,
            status=ClearanceStatus.APPROVED
        )

        dummy_clearance_file2 = SimpleUploadedFile(
            "clearance2.pdf",
            b"%PDF-1.4\nClearance content 2",
            content_type="application/pdf"
        )
        self.clearance2 = StudentClearance.objects.create(
            user=self.student2,
            file=dummy_clearance_file2,
            status=ClearanceStatus.APPROVED
        )

    def _get_dummy_receipt(self, filename="receipt.png"):
        png_header = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        return SimpleUploadedFile(
            filename,
            png_header + b"\x00\x00\x00\x01\x08\x06\x00\x00\x00",
            content_type="image/png"
        )

    def test_duplicate_or_number_returns_clean_400_bad_request(self):
        """
        Duplicate O.R. numbers (case-insensitive and trimmed) must return a clean
        400 Bad Request JSON error with 'or_number' key rather than a 500 error.
        """
        req1 = CredentialRequest.objects.create(
            user=self.student,
            credential_type=self.cred_type,
            status=RequestStatus.PAYMENT_PENDING
        )
        req2 = CredentialRequest.objects.create(
            user=self.student2,
            credential_type=self.cred_type,
            status=RequestStatus.PAYMENT_PENDING
        )

        self.client.force_authenticate(user=self.student)
        url = reverse('payment-list')

        # First payment with OR-998811
        resp1 = self.client.post(
            url,
            {
                'request': str(req1.id),
                'amount': '150.00',
                'or_number': 'OR-998811',
                'receipt_image': self._get_dummy_receipt('r1.png')
            },
            format='multipart'
        )
        self.assertEqual(resp1.status_code, status.HTTP_201_CREATED)

        # Second payment with same OR number, different casing and whitespace
        self.client.force_authenticate(user=self.student2)
        resp2 = self.client.post(
            url,
            {
                'request': str(req2.id),
                'amount': '150.00',
                'or_number': '  or-998811  ',
                'receipt_image': self._get_dummy_receipt('r2.png')
            },
            format='multipart'
        )
        self.assertEqual(resp2.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('or_number', resp2.data)
        self.assertIn(
            'This Official Receipt (O.R.) number is already in use.',
            resp2.data['or_number'][0]
        )

    def test_payment_submission_transitions_to_for_verification(self):
        """
        When a student submits payment proof while in PAYMENT_PENDING,
        the request automatically transitions to FOR_VERIFICATION.
        """
        req = CredentialRequest.objects.create(
            user=self.student,
            credential_type=self.cred_type,
            status=RequestStatus.PAYMENT_PENDING
        )

        payment = PaymentService.submit_payment(
            actor=self.student,
            request=req,
            amount=Decimal('150.00'),
            receipt_image=self._get_dummy_receipt('r_fv.png'),
            receipt_reference_number='OR-FV-001'
        )
        self.assertIsNotNone(payment.id)

        req.refresh_from_db()
        self.assertEqual(req.status, RequestStatus.FOR_VERIFICATION)

        # Staff cannot verify payment -> raises PermissionDenied
        with self.assertRaises(PermissionDenied):
            PaymentService.verify_payment(
                actor=self.staff1,
                payment=payment,
                action='VERIFY'
            )

        # Registrar verifies payment -> transitions to PAYMENT_VERIFIED
        PaymentService.verify_payment(
            actor=self.registrar,
            payment=payment,
            action='VERIFY'
        )
        req.refresh_from_db()
        self.assertEqual(req.status, RequestStatus.PAYMENT_VERIFIED)

    def test_request_status_strictly_preserved_during_assignment(self):
        """
        Assigning or reassigning a request to a staff member must strictly preserve
        its current status (PENDING stays PENDING, PAYMENT_PENDING stays
        PAYMENT_PENDING, FOR_VERIFICATION stays FOR_VERIFICATION).
        """
        self.client.force_authenticate(user=self.registrar)

        # 1. Unverified requests return 400 when attempting staff assignment
        for unverified_st in [
            RequestStatus.PENDING,
            RequestStatus.REQUIREMENTS_VERIFICATION,
            RequestStatus.PAYMENT_PENDING,
            RequestStatus.FOR_VERIFICATION,
        ]:
            req_unverified = CredentialRequest.objects.create(
                user=self.student,
                credential_type=self.cred_type,
                status=unverified_st,
            )
            assign_url = reverse(
                'credentialrequest-assign', kwargs={'pk': req_unverified.id}
            )
            res = self.client.post(
                assign_url,
                {'assigned_staff': self.staff1.username},
                format='json',
            )
            self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertIn('unverified', str(res.data).lower())

        # 2. Verified request: PROCESSING preserves status on assignment
        req_proc = CredentialRequest.objects.create(
            user=self.student,
            credential_type=self.cred_type,
            status=RequestStatus.PROCESSING,
        )
        assign_url_proc = reverse(
            'credentialrequest-assign', kwargs={'pk': req_proc.id}
        )
        res_proc = self.client.post(
            assign_url_proc,
            {'assigned_staff': self.staff1.username},
            format='json',
        )
        self.assertEqual(res_proc.status_code, status.HTTP_200_OK)
        req_proc.refresh_from_db()
        self.assertEqual(req_proc.status, RequestStatus.PROCESSING)
        self.assertEqual(req_proc.assigned_staff, self.staff1)

        # 3. Verified request: READY_FOR_RELEASE preserves status on assignment
        req_ready = CredentialRequest.objects.create(
            user=self.student,
            credential_type=self.cred_type,
            status=RequestStatus.READY_FOR_RELEASE,
        )
        assign_url_ready = reverse(
            'credentialrequest-assign', kwargs={'pk': req_ready.id}
        )
        res_ready = self.client.post(
            assign_url_ready,
            {'assigned_staff': self.staff2.username},
            format='json',
        )
        self.assertEqual(res_ready.status_code, status.HTTP_200_OK)
        req_ready.refresh_from_db()
        self.assertEqual(req_ready.status, RequestStatus.READY_FOR_RELEASE)
        self.assertEqual(req_ready.assigned_staff, self.staff2)

    def test_assign_only_active_staff_members(self):
        """
        Only active users with role == 'STAFF' can be assigned to requests.
        Assigning student, registrar, or inactive staff returns 400 Bad Request.
        """
        self.client.force_authenticate(user=self.registrar)
        req = CredentialRequest.objects.create(
            user=self.student,
            credential_type=self.cred_type,
            status=RequestStatus.PROCESSING,
        )
        assign_url = reverse('credentialrequest-assign', kwargs={'pk': req.id})

        # Try assigning to student
        res_student = self.client.post(
            assign_url,
            {'assigned_staff': self.student.username},
            format='json'
        )
        self.assertEqual(res_student.status_code, status.HTTP_400_BAD_REQUEST)

        # Inactive staff
        inactive_staff = User.objects.create_user(
            username='inactive_staff',
            password='password123',
            email='inactive_staff@test.com',
            role=Role.STAFF,
            is_active=False
        )
        res_inactive = self.client.post(
            assign_url,
            {'assigned_staff': inactive_staff.username},
            format='json'
        )
        self.assertEqual(res_inactive.status_code, status.HTTP_400_BAD_REQUEST)

        # Active staff succeeds
        res_active = self.client.post(
            assign_url,
            {'assigned_staff': self.staff1.username},
            format='json'
        )
        self.assertEqual(res_active.status_code, status.HTTP_200_OK)

    def test_role_change_and_deactivation_unassigns_open_requests(self):
        """
        When a staff user's role is changed away from STAFF or their account
        is deactivated, any open (non-terminal) requests assigned to them are
        automatically unassigned. Terminal requests (RELEASED) remain untouched.
        """
        # Create open request assigned to staff1
        open_req = CredentialRequest.objects.create(
            user=self.student,
            credential_type=self.cred_type,
            status=RequestStatus.PENDING,
            assigned_staff=self.staff1,
            in_process_queue=True,
            remarks="[Assigned to: staff1_qa]"
        )

        # Create terminal request assigned to staff1
        released_req = CredentialRequest.objects.create(
            user=self.student,
            credential_type=self.cred_type,
            status=RequestStatus.RELEASED,
            assigned_staff=self.staff1,
            in_process_queue=False
        )

        # Admin changes staff1 role away from STAFF (to STUDENT)
        AccountService.update_user(
            actor=self.admin,
            user=self.staff1,
            validated_data={'role': Role.STUDENT}
        )

        open_req.refresh_from_db()
        released_req.refresh_from_db()

        # Open request is unassigned
        self.assertIsNone(open_req.assigned_staff)
        self.assertFalse(open_req.in_process_queue)
        self.assertNotIn('[Assigned to: staff1_qa]', open_req.remarks)

        # Terminal request remains intact
        self.assertEqual(released_req.assigned_staff, self.staff1)

        # Now assign open request to staff2, then deactivate staff2
        open_req.assigned_staff = self.staff2
        open_req.in_process_queue = True
        open_req.save()

        AccountService.deactivate_user(actor=self.admin, user=self.staff2)

        open_req.refresh_from_db()
        self.assertIsNone(open_req.assigned_staff)
        self.assertFalse(open_req.in_process_queue)

    def test_edge_06_copy_count_upper_bound_validation(self):
        """
        TC-EDGE-06: Request creation with copy count exceeding bounds
        (e.g. copies > 100 or copies < 1) must return 400 Bad Request.
        """
        self.client.force_authenticate(user=self.student)
        url = reverse('credentialrequest-list')

        # 1. Copies exceeding 100
        resp_too_high = self.client.post(
            url,
            {
                'credential_type': self.cred_type.id,
                'purpose': 'Employment',
                'copies': 999999,
            },
            format='json'
        )
        self.assertEqual(resp_too_high.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('copies', resp_too_high.data)

        # 2. Copies less than 1
        resp_zero = self.client.post(
            url,
            {
                'credential_type': self.cred_type.id,
                'purpose': 'Employment',
                'copies': 0,
            },
            format='json'
        )
        self.assertEqual(resp_zero.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('copies', resp_zero.data)

        # 3. Multi-document items with copies exceeding 100
        resp_items = self.client.post(
            url,
            {
                'credential_type': self.cred_type.id,
                'purpose': 'Employment',
                'document_items': [
                    {'credential_type_id': self.cred_type.id, 'copies': 150}
                ],
            },
            format='json'
        )
        self.assertEqual(resp_items.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('document_items', resp_items.data)

        # 4. Valid copies within bounds (1-100)
        resp_valid = self.client.post(
            url,
            {
                'credential_type': self.cred_type.id,
                'purpose': 'Employment',
                'copies': 5,
            },
            format='json'
        )
        self.assertEqual(resp_valid.status_code, status.HTTP_201_CREATED)

    def test_edge_09_audit_log_deleted_user_not_misattributed_to_admin(self):
        """
        TC-EDGE-09: When an audit log actor is deleted (actor is None),
        the audit log entry must NOT fall back to attributing the action to
        the viewing admin. Instead, it must return 'Deleted User' or preserved
        actor metadata.
        """
        temp_user = User.objects.create_user(
            username='temp_staff',
            password='password123',
            email='temp_staff@test.com',
            role=Role.STAFF
        )
        temp_id = temp_user.id

        # 1. Audit log with metadata preserving username and id
        log_with_meta = AuditLog.objects.create(
            actor=temp_user,
            action='CREDENTIAL_REQUEST_UPDATED',
            object_type='CredentialRequest',
            object_id='101',
            metadata={
                'actor_id': temp_id,
                'actor_username': 'temp_staff'
            }
        )

        # 2. Audit log without actor metadata
        log_without_meta = AuditLog.objects.create(
            actor=temp_user,
            action='CREDENTIAL_REQUEST_UPDATED',
            object_type='CredentialRequest',
            object_id='102',
            metadata={}
        )

        # Delete temp_user from DB -> actor FK becomes None
        temp_user.delete()

        log_with_meta.refresh_from_db()
        log_without_meta.refresh_from_db()
        self.assertIsNone(log_with_meta.actor)
        self.assertIsNone(log_without_meta.actor)

        # Admin requests audit logs
        self.client.force_authenticate(user=self.admin)
        url = reverse('audit-logs')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        logs_data = {item['id']: item for item in resp.data}

        # Verify log_with_meta preserved username
        item_meta = logs_data[f"audit-{log_with_meta.id}"]
        self.assertEqual(item_meta['actor'], 'temp_staff')
        self.assertNotEqual(item_meta['actor'], self.admin.username)
        self.assertEqual(item_meta['actorId'], str(temp_id))

        # Verify log_without_meta defaults to 'Deleted User'
        item_no_meta = logs_data[f"audit-{log_without_meta.id}"]
        self.assertEqual(item_no_meta['actor'], 'Deleted User')
        self.assertNotEqual(item_no_meta['actor'], self.admin.username)
        self.assertEqual(item_no_meta['actorId'], 'deleted')

    def test_enrolled_student_cannot_submit_graduate_only_purposes(self):
        """Enrolled student cannot request graduate-only purposes (e.g. Board Exam)."""
        student = User.objects.create_user(
            username='stud_enrolled',
            password='password123',
            email='stud_enrolled@test.com',
            role=Role.STUDENT,
            year_level='2nd year'
        )
        StudentClearance.objects.create(
            user=student,
            status=ClearanceStatus.APPROVED,
            file=SimpleUploadedFile("clr.pdf", b"pdf", content_type="application/pdf")
        )
        self.client.force_authenticate(user=student)
        url = reverse('credentialrequest-list')
        payload = {
            'credential_type': self.cred_type.id,
            'remarks': 'For Board Exam [Copies: 1]',
            'date_of_graduation': 'May 2026'
        }
        res = self.client.post(url, payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('remarks', str(res.data).lower())

    def test_alumnus_can_submit_graduate_only_purposes(self):
        """Alumnus user can submit graduate-only purposes."""
        alumnus = User.objects.create_user(
            username='stud_alumnus',
            password='password123',
            email='stud_alumnus@test.com',
            role=Role.STUDENT,
            year_level='Alumnus'
        )
        StudentClearance.objects.create(
            user=alumnus,
            status=ClearanceStatus.APPROVED,
            file=SimpleUploadedFile("clr.pdf", b"pdf", content_type="application/pdf")
        )
        self.client.force_authenticate(user=alumnus)
        url = reverse('credentialrequest-list')
        payload = {
            'credential_type': self.cred_type.id,
            'remarks': 'For Board Exam [Copies: 1]',
            'date_of_graduation': 'June 2024'
        }
        res = self.client.post(url, payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    def test_admin_can_update_user_id(self):
        """Admin can update username / student_id for target accounts."""
        target_student = User.objects.create_user(
            username='stud_orig_id',
            password='password123',
            email='stud_orig@test.com',
            role=Role.STUDENT,
        )
        self.client.force_authenticate(user=self.admin)
        url = reverse('user-detail', kwargs={'pk': target_student.id})
        res = self.client.patch(url, {'student_id': 'stud_new_id_2026'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        target_student.refresh_from_db()
        self.assertEqual(target_student.username, 'stud_new_id_2026')

    def test_admin_updating_user_id_to_duplicate_fails(self):
        """Admin cannot update user ID to an existing case-insensitive username."""
        User.objects.create_user(
            username='existing_user_id',
            password='password123',
            email='exist@test.com',
            role=Role.STUDENT,
        )
        target_staff = User.objects.create_user(
            username='staff_to_edit',
            password='password123',
            email='staff_edit@test.com',
            role=Role.STAFF,
        )
        self.client.force_authenticate(user=self.admin)
        url = reverse('user-detail', kwargs={'pk': target_staff.id})
        res = self.client.patch(
            url, {'username': 'EXISTING_USER_ID'}, format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('already registered', str(res.data).lower())

    def test_self_profile_update_cannot_change_user_id(self):
        """Non-admin user cannot change user ID via self-profile /api/users/me/."""
        student = User.objects.create_user(
            username='self_student_id',
            password='password123',
            email='self_stud@test.com',
            role=Role.STUDENT,
        )
        self.client.force_authenticate(user=student)
        url = reverse('user-me')
        res = self.client.patch(
            url,
            {'username': 'hacked_id', 'student_id': 'hacked_id'},
            format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        student.refresh_from_db()
        self.assertEqual(student.username, 'self_student_id')

    def test_credential_request_serialization_includes_user_category(self):
        """Request serializer includes user_category and date_of_graduation."""
        alumnus = User.objects.create_user(
            username='alumnus_req_user',
            password='password123',
            email='alumnus_req@test.com',
            role=Role.STUDENT,
            year_level='Alumnus'
        )
        StudentClearance.objects.create(
            user=alumnus,
            status=ClearanceStatus.APPROVED,
            file=SimpleUploadedFile("clr.pdf", b"pdf", content_type="application/pdf")
        )
        self.client.force_authenticate(user=alumnus)
        url = reverse('credentialrequest-list')
        payload = {
            'credential_type': self.cred_type.id,
            'remarks': 'For Board Exam [Graduation: March 2024]',
            'date_of_graduation': 'March 2024'
        }
        res = self.client.post(url, payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data.get('user_category'), 'alumnus')
        self.assertEqual(res.data.get('year_level'), 'Alumnus')
        self.assertEqual(res.data.get('date_of_graduation'), 'March 2024')

    def test_notification_deduplication_guard(self):
        """NotificationService.create_notification deduplicates within 60 seconds."""
        user = User.objects.create_user(
            username='notif_dedup_user',
            password='password123',
            email='notif_dedup@test.com',
            role=Role.STUDENT,
        )
        notif1 = NotificationService.create_notification(
            recipient=user,
            event_type=NotificationEvent.REQUEST_CREATED,
            message="Test message",
            related_object_type="CredentialRequest",
            related_object_id="12345",
        )
        notif2 = NotificationService.create_notification(
            recipient=user,
            event_type=NotificationEvent.REQUEST_CREATED,
            message="Test message duplicate",
            related_object_type="CredentialRequest",
            related_object_id="12345",
        )
        self.assertEqual(notif1.id, notif2.id)
        self.assertEqual(
            Notification.objects.filter(
                user=user,
                event_type=NotificationEvent.REQUEST_CREATED,
                related_object_id="12345"
            ).count(),
            1
        )

    def test_send_request_notification_dispatches_email(self):
        """send_request_notification creates notification and sends email."""
        user = User.objects.create_user(
            username='email_notif_user',
            first_name='Daisy',
            last_name='Traya',
            password='password123',
            email='daisy.traya@ustp.edu.ph',
            role=Role.STUDENT,
        )
        notif = NotificationService.send_request_notification(
            user=user,
            title="Request Ready",
            message="Your credential is ready.",
            reference_id="REQ-99999",
            send_email=True,
        )
        self.assertIsNotNone(notif)
        time.sleep(0.1)  # wait for daemon thread
        self.assertGreaterEqual(len(mail.outbox), 1)
        sent_email = mail.outbox[-1]
        self.assertIn("daisy.traya@ustp.edu.ph", sent_email.to)
        self.assertIn("RegQuest - Request Ready", sent_email.subject)
        self.assertIn("REQ-99999", sent_email.body)

    def test_self_profile_update_persists_editable_fields(self):
        """PATCH /api/users/me/ updates editable profile fields."""
        student = User.objects.create_user(
            username='self_profile_updater',
            first_name='OldFirst',
            last_name='OldLast',
            password='password123',
            email='old@test.com',
            role=Role.STUDENT,
        )
        self.client.force_authenticate(user=student)
        url = reverse('user-me')
        payload = {
            'first_name': 'NewFirst',
            'last_name': 'NewLast',
            'contact_number': '09123456789',
            'birth_date': '2002-05-15',
            'year_level': '3rd year',
        }
        res = self.client.patch(url, payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        student.refresh_from_db()
        self.assertEqual(student.first_name, 'NewFirst')
        self.assertEqual(student.last_name, 'NewLast')
        self.assertEqual(student.contact_number, '09123456789')
        self.assertEqual(str(student.birth_date), '2002-05-15')
        self.assertEqual(student.year_level, '3rd year')

    def test_credential_request_creation_generates_single_student_notification(self):
        """Submitting a request creates exactly 1 student notification and 1 email."""
        mail.outbox = []
        student = User.objects.create_user(
            username='single_notif_student',
            first_name='StudentName',
            password='password123',
            email='single_notif@test.com',
            role=Role.STUDENT,
            year_level='2nd year',
        )
        StudentClearance.objects.create(
            user=student,
            status=ClearanceStatus.APPROVED,
            file=SimpleUploadedFile("clr.pdf", b"pdf", content_type="application/pdf"),
        )
        self.client.force_authenticate(user=student)
        url = reverse('credentialrequest-list')
        payload = {
            'credential_type': self.cred_type.id,
            'remarks': 'Single notification test',
        }
        res = self.client.post(url, payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        self.assertEqual(
            Notification.objects.filter(
                user=student,
                title="Request Submitted"
            ).count(),
            1
        )
        time.sleep(0.1)
        student_emails = [m for m in mail.outbox if 'single_notif@test.com' in m.to]
        self.assertEqual(len(student_emails), 1)

    def test_send_request_notification_deduplicates_by_title_and_reference(self):
        """Deduplicates by (user, title, ref) ignoring slight message differences."""
        mail.outbox = []
        user = User.objects.create_user(
            username='dedup_title_user',
            first_name='Daisy',
            password='password123',
            email='dedup_title@ustp.edu.ph',
            role=Role.STUDENT,
        )
        notif1 = NotificationService.send_request_notification(
            user=user,
            title="Request Submitted",
            message=(
                "Your credential request (REQ-1) for Diploma has been submitted "
                "successfully. Status: Pending."
            ),
            reference_id="REQ-1",
            send_email=True,
        )
        # Call again with slightly different message wording within 60 seconds
        notif2 = NotificationService.send_request_notification(
            user=user,
            title="Request Submitted",
            message=(
                "Your credential request (REQ-1) for Diploma has been submitted. "
                "Status: Pending."
            ),
            reference_id="REQ-1",
            send_email=True,
        )
        self.assertEqual(notif1.id, notif2.id)
        self.assertEqual(
            Notification.objects.filter(
                user=user,
                title="Request Submitted"
            ).count(),
            1
        )
        time.sleep(0.1)
        # Exactly 1 email sent, second duplicate invocation was skipped
        self.assertEqual(len(mail.outbox), 1)

    def test_staff_forbidden_from_clearance_review_and_registrar_allowed(self):
        """
        Staff attempting to review/verify clearance must receive 403 Forbidden,
        while Registrar Frontdesk is permitted.
        """
        clearance = StudentClearance.objects.create(
            user=self.student,
            file=self._get_dummy_receipt('clr_duty.pdf'),
            status=ClearanceStatus.PENDING,
        )
        url = reverse('studentclearance-review', args=[clearance.id])

        # 1. Staff attempt -> 403 Forbidden
        self.client.force_authenticate(user=self.staff1)
        res_staff = self.client.patch(url, {'status': 'APPROVED'})
        self.assertEqual(res_staff.status_code, status.HTTP_403_FORBIDDEN)
        clearance.refresh_from_db()
        self.assertEqual(clearance.status, ClearanceStatus.PENDING)

        # 2. Registrar Frontdesk attempt -> 200 OK
        self.client.force_authenticate(user=self.registrar)
        res_reg = self.client.patch(url, {'status': 'APPROVED'})
        self.assertEqual(res_reg.status_code, status.HTTP_200_OK)
        clearance.refresh_from_db()
        self.assertEqual(clearance.status, ClearanceStatus.APPROVED)

    def test_staff_forbidden_from_payment_verify_and_registrar_allowed(self):
        """
        Staff attempting to verify OTC payments must receive 403 Forbidden,
        while Registrar Frontdesk is permitted.
        """
        req = CredentialRequest.objects.create(
            user=self.student,
            credential_type=self.cred_type,
            status=RequestStatus.FOR_VERIFICATION,
        )
        payment = PaymentService.submit_payment(
            actor=self.student,
            request=req,
            amount=Decimal('100.00'),
            receipt_image=self._get_dummy_receipt('otc_duty.png'),
            receipt_reference_number='OR-DUTY-123',
        )
        url = reverse('payment-verify', args=[payment.id])

        # 1. Staff attempt -> 403 Forbidden
        self.client.force_authenticate(user=self.staff1)
        res_staff = self.client.patch(url, {'action': 'VERIFY'})
        self.assertEqual(res_staff.status_code, status.HTTP_403_FORBIDDEN)

        # 2. Registrar Frontdesk attempt -> 200 OK
        self.client.force_authenticate(user=self.registrar)
        res_reg = self.client.patch(url, {'action': 'VERIFY'})
        self.assertEqual(res_reg.status_code, status.HTTP_200_OK)
        req.refresh_from_db()
        self.assertEqual(req.status, RequestStatus.PAYMENT_VERIFIED)

    def test_staff_forbidden_from_transitioning_unverified_request(self):
        """
        Staff attempting to transition an unverified request into Processing
        or any other state must receive 403 Forbidden.
        """
        req = CredentialRequest.objects.create(
            user=self.student,
            credential_type=self.cred_type,
            status=RequestStatus.PENDING,
        )
        url = reverse('credentialrequest-transition', args=[req.id])
        self.client.force_authenticate(user=self.staff1)

        res = self.client.patch(url, {'status': RequestStatus.PROCESSING})
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        req.refresh_from_db()
        self.assertEqual(req.status, RequestStatus.PENDING)

        # Service call directly raises PermissionDenied
        from credentials.services import CredentialRequestService
        with self.assertRaises(PermissionDenied):
            CredentialRequestService.transition_request(
                actor=self.staff1,
                credential_request=req,
                new_status=RequestStatus.PROCESSING,
            )

    def test_staff_queue_only_shows_verified_requests(self):
        """
        Staff requests list endpoint returns only verified requests (Processing+),
        excluding Pending, Requirements Verification, Payment Pending, and
        For Verification. Registrar sees the full lifecycle.
        """
        req_pending = CredentialRequest.objects.create(
            user=self.student,
            credential_type=self.cred_type,
            status=RequestStatus.PENDING,
        )
        req_proc = CredentialRequest.objects.create(
            user=self.student,
            credential_type=self.cred_type,
            status=RequestStatus.PROCESSING,
        )
        req_ready = CredentialRequest.objects.create(
            user=self.student,
            credential_type=self.cred_type,
            status=RequestStatus.READY_FOR_RELEASE,
        )
        url = reverse('credentialrequest-list')

        # Staff queue
        self.client.force_authenticate(user=self.staff1)
        res_staff = self.client.get(url)
        self.assertEqual(res_staff.status_code, status.HTTP_200_OK)
        staff_ids = [r['id'] for r in res_staff.data]
        self.assertNotIn(str(req_pending.id), staff_ids)
        self.assertIn(str(req_proc.id), staff_ids)
        self.assertIn(str(req_ready.id), staff_ids)

        # Registrar queue
        self.client.force_authenticate(user=self.registrar)
        res_reg = self.client.get(url)
        self.assertEqual(res_reg.status_code, status.HTTP_200_OK)
        reg_ids = [r['id'] for r in res_reg.data]
        self.assertIn(str(req_pending.id), reg_ids)
        self.assertIn(str(req_proc.id), reg_ids)
        self.assertIn(str(req_ready.id), reg_ids)

    def test_notification_role_routing_intake_and_fulfillment(self):
        """
        Verify strict role-based routing:
        - Intake alerts (Request Created, Clearance Uploaded, Payment Submitted)
          reach Registrar Frontdesk and Admin, NOT Staff.
        - Fulfillment alerts reach Staff only once verified/assigned.
        - Student receives only their milestones.
        """
        # 1. Request Created
        req = CredentialRequestService.create_request(
            actor=self.student,
            validated_data={
                'credential_type': self.cred_type,
                'status': 'PENDING'
            }
        )
        self.assertTrue(
            Notification.objects.filter(
                user=self.student,
                event_type=NotificationEvent.REQUEST_CREATED,
                related_object_id=str(req.id)
            ).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                user=self.registrar,
                event_type=NotificationEvent.REQUEST_CREATED,
                related_object_id=str(req.id)
            ).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                user=self.admin,
                event_type=NotificationEvent.REQUEST_CREATED,
                related_object_id=str(req.id)
            ).exists()
        )
        self.assertFalse(
            Notification.objects.filter(
                user=self.staff1,
                event_type=NotificationEvent.REQUEST_CREATED,
            ).exists()
        )

        # 2. Clearance Uploaded
        clearance = StudentClearanceService.submit_clearance(
            actor=self.student,
            file=self._get_dummy_receipt('clr_route.pdf')
        )
        self.assertTrue(
            Notification.objects.filter(
                user=self.registrar,
                event_type=NotificationEvent.CLEARANCE_SUBMITTED,
                related_object_id=str(clearance.id)
            ).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                user=self.admin,
                event_type=NotificationEvent.CLEARANCE_SUBMITTED,
                related_object_id=str(clearance.id)
            ).exists()
        )
        self.assertFalse(
            Notification.objects.filter(
                user=self.staff1,
                event_type=NotificationEvent.CLEARANCE_SUBMITTED,
            ).exists()
        )

        # 3. Payment Uploaded
        req.status = RequestStatus.PAYMENT_PENDING
        req.save()
        payment = PaymentService.submit_payment(
            actor=self.student,
            request=req,
            amount=150.00,
            receipt_image=self._get_dummy_receipt('pay_route.pdf'),
            receipt_reference_number="OR-ROUTE-1"
        )
        self.assertTrue(
            Notification.objects.filter(
                user=self.registrar,
                event_type=NotificationEvent.PAYMENT_SUBMITTED,
                related_object_id=str(payment.id)
            ).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                user=self.admin,
                event_type=NotificationEvent.PAYMENT_SUBMITTED,
                related_object_id=str(payment.id)
            ).exists()
        )
        self.assertFalse(
            Notification.objects.filter(
                user=self.staff1,
                event_type=NotificationEvent.PAYMENT_SUBMITTED,
            ).exists()
        )

        # 4. Payment Verified
        PaymentService.verify_payment(
            actor=self.registrar,
            payment=payment,
            action='VERIFY'
        )
        req.refresh_from_db()
        self.assertEqual(req.status, RequestStatus.PAYMENT_VERIFIED)
        self.assertTrue(
            Notification.objects.filter(
                user=self.student,
                event_type=NotificationEvent.PAYMENT_VERIFIED,
                related_object_id=str(req.id)
            ).exists()
        )

        # 5. Assigned & Processed
        CredentialRequestService.transition_request(
            actor=self.registrar,
            credential_request=req,
            new_status=RequestStatus.PROCESSING,
            assigned_staff=self.staff1
        )
        self.assertTrue(
            Notification.objects.filter(
                user=self.staff1,
                event_type=NotificationEvent.REQUEST_ASSIGNED,
                related_object_id=str(req.id)
            ).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                user=self.student,
                title=f"Request Processing ({req.tracking_number})"
            ).exists()
        )

        # 6. Ready for Release
        CredentialRequestService.transition_request(
            actor=self.registrar,
            credential_request=req,
            new_status=RequestStatus.READY_FOR_RELEASE
        )
        self.assertTrue(
            Notification.objects.filter(
                user=self.student,
                title=f"Ready for Release ({req.tracking_number})"
            ).exists()
        )

        # 7. Released
        CredentialRequestService.transition_request(
            actor=self.staff1,
            credential_request=req,
            new_status=RequestStatus.RELEASED
        )
        self.assertTrue(
            Notification.objects.filter(
                user=self.student,
                title=f"Document Released ({req.tracking_number})"
            ).exists()
        )

    def test_notification_unread_refresh_prevents_duplicate_spam(self):
        """
        Re-uploads or repeated saves do not duplicate unread notifications
        for the same recipient, title, and reference ID.
        """
        notif1 = NotificationService.create_notification(
            recipient=self.student,
            event_type=NotificationEvent.CLEARANCE_SUBMITTED,
            title="Clearance Uploaded",
            message="Initial clearance upload",
            related_object_type="StudentClearance",
            related_object_id="clr-repeat-1"
        )
        self.assertFalse(notif1.is_read)

        # Simulate a repeated upload / save
        notif2 = NotificationService.create_notification(
            recipient=self.student,
            event_type=NotificationEvent.CLEARANCE_SUBMITTED,
            title="Clearance Uploaded",
            message="Re-uploaded clearance with new signature",
            related_object_type="StudentClearance",
            related_object_id="clr-repeat-1"
        )
        self.assertEqual(notif1.id, notif2.id)
        self.assertEqual(
            Notification.objects.filter(
                user=self.student,
                title="Clearance Uploaded",
                related_object_id="clr-repeat-1"
            ).count(),
            1
        )
        notif1.refresh_from_db()
        self.assertEqual(notif1.message, "Re-uploaded clearance with new signature")

    def test_staff_notification_feed_filters_unverified_intake_alerts(self):
        """
        GET /api/notifications/ for Staff excludes unverified intake alerts
        (REQUEST_CREATED, CLEARANCE_SUBMITTED, PAYMENT_SUBMITTED) while
        including fulfillment alerts (REQUEST_ASSIGNED).
        Admin includes intake alerts.
        """
        # Create notifications directly
        Notification.objects.create(
            user=self.staff1,
            title="New Request Submitted",
            event_type=NotificationEvent.REQUEST_CREATED,
            message="Request submitted alert"
        )
        Notification.objects.create(
            user=self.staff1,
            title="Clearance Uploaded",
            event_type=NotificationEvent.CLEARANCE_SUBMITTED,
            message="Clearance alert"
        )
        Notification.objects.create(
            user=self.staff1,
            title="Payment Submitted",
            event_type=NotificationEvent.PAYMENT_SUBMITTED,
            message="Payment alert"
        )
        notif_assigned = Notification.objects.create(
            user=self.staff1,
            title="Request Assigned",
            event_type=NotificationEvent.REQUEST_ASSIGNED,
            message="Fulfillment assignment alert"
        )

        url = reverse('notification-list')

        # Staff query
        self.client.force_authenticate(user=self.staff1)
        res_staff = self.client.get(url)
        self.assertEqual(res_staff.status_code, status.HTTP_200_OK)
        staff_event_types = [n['event_type'] for n in res_staff.data.get('results', [])]
        self.assertNotIn(NotificationEvent.REQUEST_CREATED, staff_event_types)
        self.assertNotIn(NotificationEvent.CLEARANCE_SUBMITTED, staff_event_types)
        self.assertNotIn(NotificationEvent.PAYMENT_SUBMITTED, staff_event_types)
        self.assertIn(NotificationEvent.REQUEST_ASSIGNED, staff_event_types)
        staff_ids = [n['id'] for n in res_staff.data.get('results', [])]
        self.assertIn(str(notif_assigned.id), staff_ids)

        # Admin query includes intake alerts
        notif_admin = Notification.objects.create(
            user=self.admin,
            title="New Request Submitted",
            event_type=NotificationEvent.REQUEST_CREATED,
            message="Admin intake alert"
        )
        self.client.force_authenticate(user=self.admin)
        res_admin = self.client.get(url)
        self.assertEqual(res_admin.status_code, status.HTTP_200_OK)
        admin_ids = [n['id'] for n in res_admin.data.get('results', [])]
        self.assertIn(str(notif_admin.id), admin_ids)
