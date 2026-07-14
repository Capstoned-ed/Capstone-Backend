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
        self.assertEqual(Notification.objects.count(), initial_count + 1)
        new_notif = Notification.objects.latest('created_at')
        self.assertEqual(new_notif.user, self.user1)
        self.assertEqual(new_notif.event_type, NotificationEvent.REQUEST_CREATED)
        self.assertEqual(new_notif.related_object_type, 'CredentialRequest')
        self.assertEqual(new_notif.related_object_id, str(req.id))
