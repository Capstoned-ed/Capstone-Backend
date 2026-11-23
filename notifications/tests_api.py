from rest_framework.test import APITestCase
from rest_framework import status
from django.contrib.auth import get_user_model
from django.urls import reverse
from .models import Notification, NotificationEvent
from accounts.models import Role
from accounts.services import AccountService
from credentials.models import CredentialType
from credentials.services import CredentialRequestService
import uuid

User = get_user_model()


class NotificationAPITests(APITestCase):
    def setUp(self):
        self.user1 = User.objects.create_user(
            username='user1', email='u1@test.com', password='p', role=Role.STUDENT
        )
        self.user2 = User.objects.create_user(
            username='user2', email='u2@test.com', password='p', role=Role.STUDENT
        )
        self.admin = User.objects.create_user(
            username='admin1', email='a1@test.com', password='p', role=Role.ADMIN
        )

        self.notif1 = Notification.objects.create(
            user=self.user1,
            event_type=NotificationEvent.ACCOUNT_CREATED,
            message="Welcome",
            related_object_type="User",
            related_object_id=str(self.user1.id)
        )
        self.notif2 = Notification.objects.create(
            user=self.user1,
            event_type=NotificationEvent.REQUEST_CREATED,
            message="Request 1",
            related_object_type="CredentialRequest",
            related_object_id=str(uuid.uuid4())
        )
        self.notif3 = Notification.objects.create(
            user=self.user2,
            event_type=NotificationEvent.ACCOUNT_CREATED,
            message="Welcome 2"
        )

        self.url_list = reverse('notification-list')
        self.url_mark_all_read = reverse('notification-mark-all-read')

    def get_mark_read_url(self, notif_id):
        return reverse('notification-mark-read', kwargs={'pk': notif_id})

    def test_list_own_notifications(self):
        self.client.force_authenticate(user=self.user1)
        res = self.client.get(self.url_list)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data['results']), 2)
        # Should be ordered by -created_at
        self.assertEqual(res.data['results'][0]['id'], str(self.notif2.id))
        self.assertEqual(res.data['results'][1]['id'], str(self.notif1.id))

    def test_cannot_view_another_users_notifications(self):
        self.client.force_authenticate(user=self.user1)
        res = self.client.get(self.url_list)
        ids = [n['id'] for n in res.data['results']]
        self.assertNotIn(str(self.notif3.id), ids)

        # Direct access should be 404
        res2 = self.client.patch(self.get_mark_read_url(self.notif3.id))
        self.assertEqual(res2.status_code, status.HTTP_404_NOT_FOUND)

    def test_mark_single_notification_read(self):
        self.client.force_authenticate(user=self.user1)
        self.assertFalse(self.notif1.is_read)
        res = self.client.patch(self.get_mark_read_url(self.notif1.id))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.notif1.refresh_from_db()
        self.assertTrue(self.notif1.is_read)

    def test_mark_all_notifications_read(self):
        self.client.force_authenticate(user=self.user1)
        self.assertFalse(self.notif1.is_read)
        self.assertFalse(self.notif2.is_read)

        res = self.client.post(self.url_mark_all_read)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['updated_count'], 2)

        self.notif1.refresh_from_db()
        self.notif2.refresh_from_db()
        self.assertTrue(self.notif1.is_read)
        self.assertTrue(self.notif2.is_read)

        # Ensure user2's notification was not affected
        self.notif3.refresh_from_db()
        self.assertFalse(self.notif3.is_read)

    def test_notification_hook_account_created(self):
        initial_count = Notification.objects.count()
        AccountService.create_user(
            actor=self.admin,
            username='newuser',
            email='new@test.com',
            password='password123',
            role=Role.STUDENT
        )
        self.assertEqual(Notification.objects.count(), initial_count + 1)
        new_notif = Notification.objects.latest('created_at')
        self.assertEqual(new_notif.user.username, 'newuser')
        self.assertEqual(new_notif.event_type, NotificationEvent.ACCOUNT_CREATED)
        self.assertEqual(new_notif.related_object_type, 'User')

    def test_notification_hook_request_created(self):
        from credentials.models import StudentClearance, ClearanceStatus
        from django.core.files.uploadedfile import SimpleUploadedFile
        registrar = User.objects.create_user(
            username='registrar1',
            email='reg1@test.com',
            password='p',
            role=Role.REGISTRAR,
        )
        cfile = SimpleUploadedFile(
            "c.pdf", b"%PDF-1.4\n", content_type="application/pdf"
        )
        StudentClearance.objects.create(
            user=self.user1, file=cfile, status=ClearanceStatus.PENDING
        )
        ctype = CredentialType.objects.create(
            code='TOR', name='Transcript', price=100.00, processing_days=5
        )
        initial_count = Notification.objects.count()

        req = CredentialRequestService.create_request(
            actor=self.user1,
            validated_data={
                'credential_type': ctype,
                'status': 'PENDING'
            }
        )
        # Student + Registrar notified; Admin strictly excluded
        self.assertEqual(Notification.objects.count(), initial_count + 2)
        user_notif = Notification.objects.filter(user=self.user1).latest('created_at')
        self.assertEqual(user_notif.user, self.user1)
        self.assertEqual(user_notif.event_type, NotificationEvent.REQUEST_CREATED)
        self.assertEqual(user_notif.related_object_type, 'CredentialRequest')
        self.assertEqual(user_notif.related_object_id, str(req.id))

        reg_notif = Notification.objects.filter(user=registrar).latest('created_at')
        self.assertEqual(reg_notif.user, registrar)
        self.assertEqual(reg_notif.event_type, NotificationEvent.REQUEST_CREATED)
        self.assertEqual(reg_notif.related_object_type, 'CredentialRequest')
        self.assertEqual(reg_notif.related_object_id, str(req.id))

        self.assertFalse(
            Notification.objects.filter(
                user=self.admin,
                event_type=NotificationEvent.REQUEST_CREATED,
            ).exists()
        )

    def test_notification_hook_staff_assigned(self):
        from credentials.models import (
            CredentialType, RequestStatus, StudentClearance, ClearanceStatus
        )
        from credentials.services import CredentialRequestService
        from django.core.files.uploadedfile import SimpleUploadedFile
        cfile = SimpleUploadedFile(
            "c.pdf", b"%PDF-1.4\n", content_type="application/pdf"
        )
        StudentClearance.objects.get_or_create(
            user=self.user1, defaults={'file': cfile, 'status': ClearanceStatus.PENDING}
        )
        staff = User.objects.create_user(
            username='staff_test', email='st@test.com', password='p', role=Role.STAFF
        )
        ctype = CredentialType.objects.create(
            code='TOR2', name='Transcript 2', price=100.00, processing_days=5
        )
        req = CredentialRequestService.create_request(
            actor=self.user1,
            validated_data={'credential_type': ctype, 'status': 'PENDING'}
        )
        req.status = RequestStatus.PROCESSING
        req.save()
        CredentialRequestService.transition_request(
            actor=self.admin,
            credential_request=req,
            new_status=RequestStatus.PROCESSING,
            assigned_staff=staff
        )
        staff_notif = Notification.objects.filter(user=staff).latest('created_at')
        self.assertEqual(staff_notif.event_type, NotificationEvent.REQUEST_ASSIGNED)
        self.assertIn(req.tracking_number, staff_notif.message)

    def test_notification_hook_payment_and_clearance(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from credentials.models import (
            CredentialType, RequestStatus, StudentClearance, ClearanceStatus
        )
        from credentials.services import (
            CredentialRequestService, PaymentService, StudentClearanceService
        )
        cfile = SimpleUploadedFile(
            "c.pdf", b"%PDF-1.4\n", content_type="application/pdf"
        )
        StudentClearance.objects.get_or_create(
            user=self.user1, defaults={'file': cfile, 'status': ClearanceStatus.PENDING}
        )
        staff = User.objects.create_user(
            username='staff_test2', email='st2@test.com', password='p', role=Role.STAFF
        )
        ctype = CredentialType.objects.create(
            code='TOR3', name='Transcript 3', price=100.00, processing_days=5
        )
        req = CredentialRequestService.create_request(
            actor=self.user1,
            validated_data={'credential_type': ctype, 'status': 'PENDING'}
        )
        req.assigned_staff = staff
        req.status = RequestStatus.PAYMENT_PENDING
        req.save()

        # 1. Student uploads clearance -> staff notified
        clearance_file = SimpleUploadedFile(
            "clearance.pdf", b"%PDF-1.4\n", content_type="application/pdf"
        )
        StudentClearanceService.submit_clearance(actor=self.user1, file=clearance_file)
        clearance_notif = Notification.objects.filter(
            user=staff, event_type=NotificationEvent.CLEARANCE_SUBMITTED
        ).latest('created_at')
        self.assertIn(req.tracking_number, clearance_notif.message)

        # 2. Student uploads payment -> staff notified
        receipt_file = SimpleUploadedFile(
            "receipt.pdf", b"%PDF-1.4\n", content_type="application/pdf"
        )
        PaymentService.submit_payment(
            actor=self.user1,
            request=req,
            amount=100.00,
            receipt_image=receipt_file,
            receipt_reference_number="OR-NOTIF-1"
        )
        pay_notif = Notification.objects.filter(
            user=staff, event_type=NotificationEvent.PAYMENT_SUBMITTED
        ).latest('created_at')
        self.assertIn(req.tracking_number, pay_notif.message)
