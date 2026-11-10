from datetime import timedelta
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import Role, PasswordResetOTP
from audit.models import AuditLog
from notifications.models import Notification, NotificationEvent

User = get_user_model()


class PasswordResetOTPTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='student123',
            email='student123@ustp.edu.ph',
            password='oldPassword123!',
            role=Role.STUDENT,
            first_name='Juan',
            last_name='Dela Cruz',
            force_password_change=True,
        )
        self.request_url = reverse('password_reset_request')
        self.verify_url = reverse('password_reset_verify')
        self.confirm_url = reverse('password_reset_confirm')

    def test_request_otp_success(self):
        response = self.client.post(self.request_url, {
            'email': 'student123@ustp.edu.ph'
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('verification code has been sent', response.data['detail'])

        # Check OTP in database
        otp_record = PasswordResetOTP.objects.filter(user=self.user).first()
        self.assertIsNotNone(otp_record)
        self.assertFalse(otp_record.is_used)
        self.assertGreater(otp_record.expires_at, timezone.now())

        # Check email sent
        self.assertEqual(len(mail.outbox), 1)
        sent_email = mail.outbox[0]
        self.assertIn('student123@ustp.edu.ph', sent_email.to)
        self.assertIn('Your Verification Code is', sent_email.subject)

        # Check audit log
        audit = AuditLog.objects.filter(
            action='PASSWORD_RESET_REQUESTED',
            object_id=self.user.id
        ).first()
        self.assertIsNotNone(audit)

    def test_request_otp_by_username(self):
        response = self.client.post(self.request_url, {
            'email': 'student123'
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('student123@ustp.edu.ph', mail.outbox[0].to)

    def test_request_otp_anti_enumeration_nonexistent_email(self):
        response = self.client.post(self.request_url, {
            'email': 'nonexistent@example.com'
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('verification code has been sent', response.data['detail'])
        self.assertEqual(len(mail.outbox), 0)

    def test_request_otp_cooldown(self):
        # First request
        self.client.post(self.request_url, {'email': self.user.email})
        self.assertEqual(len(mail.outbox), 1)

        # Second immediate request should not send a second email
        self.client.post(self.request_url, {'email': self.user.email})
        self.assertEqual(len(mail.outbox), 1)

    def test_verify_otp_valid_and_invalid(self):
        self.client.post(self.request_url, {'email': self.user.email})
        # Extract OTP from email
        body = mail.outbox[0].body
        # Body format: "Your password reset verification code is: 123456"
        otp = [
            word for word in body.split()
            if len(word) == 6 and word.isdigit()
        ][0]

        # Test invalid OTP
        wrong_res = self.client.post(self.verify_url, {
            'email': self.user.email,
            'otp': '000000'
        })
        self.assertEqual(wrong_res.status_code, status.HTTP_400_BAD_REQUEST)

        # Check attempts incremented
        otp_record = PasswordResetOTP.objects.get(user=self.user, is_used=False)
        self.assertEqual(otp_record.attempts, 1)

        # Test valid OTP
        valid_res = self.client.post(self.verify_url, {
            'email': self.user.email,
            'otp': otp
        })
        self.assertEqual(valid_res.status_code, status.HTTP_200_OK)
        self.assertEqual(valid_res.data['detail'], 'Verification code is valid.')

    def test_verify_otp_brute_force_lockout(self):
        self.client.post(self.request_url, {'email': self.user.email})
        otp_record = PasswordResetOTP.objects.get(user=self.user, is_used=False)

        # Attempt 5 wrong OTPs
        for _ in range(5):
            self.client.post(self.verify_url, {
                'email': self.user.email,
                'otp': '999999'
            })

        otp_record.refresh_from_db()
        self.assertEqual(otp_record.attempts, 5)
        self.assertTrue(otp_record.is_used)

        # Even correct OTP should now be rejected
        body = mail.outbox[0].body
        correct_otp = [w for w in body.split() if len(w) == 6 and w.isdigit()][0]
        res = self.client.post(self.verify_url, {
            'email': self.user.email,
            'otp': correct_otp
        })
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_verify_otp_expired(self):
        self.client.post(self.request_url, {'email': self.user.email})
        otp_record = PasswordResetOTP.objects.get(user=self.user, is_used=False)
        otp_record.expires_at = timezone.now() - timedelta(minutes=1)
        otp_record.save()

        body = mail.outbox[0].body
        otp = [w for w in body.split() if len(w) == 6 and w.isdigit()][0]

        res = self.client.post(self.verify_url, {
            'email': self.user.email,
            'otp': otp
        })
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_confirm_password_reset_success(self):
        self.client.post(self.request_url, {'email': self.user.email})
        body = mail.outbox[0].body
        otp = [w for w in body.split() if len(w) == 6 and w.isdigit()][0]

        response = self.client.post(self.confirm_url, {
            'email': self.user.email,
            'otp': otp,
            'new_password': 'BrandNewPassword2026!'
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('Password has been reset', response.data['detail'])

        # Verify user can authenticate with new password
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('BrandNewPassword2026!'))
        self.assertFalse(self.user.force_password_change)

        # Verify OTP is marked used
        otp_record = PasswordResetOTP.objects.get(user=self.user)
        self.assertTrue(otp_record.is_used)

        # Verify Audit Log
        audit = AuditLog.objects.filter(
            action='PASSWORD_RESET_COMPLETED',
            object_id=self.user.id
        ).first()
        self.assertIsNotNone(audit)

        # Verify Notification
        notif = Notification.objects.filter(
            user=self.user,
            event_type=NotificationEvent.PASSWORD_RESET
        ).first()
        self.assertIsNotNone(notif)

    def test_confirm_password_reset_short_password_rejected(self):
        self.client.post(self.request_url, {'email': self.user.email})
        body = mail.outbox[0].body
        otp = [w for w in body.split() if len(w) == 6 and w.isdigit()][0]

        response = self.client.post(self.confirm_url, {
            'email': self.user.email,
            'otp': otp,
            'new_password': '123'
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

