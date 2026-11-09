from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from decimal import Decimal
from accounts.models import Role
from .models import CredentialType, CredentialRequest, RequestStatus

User = get_user_model()


class CredentialRequestModelTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(
            username='20233206967',
            email='s@test.com',
            password='p',
            role=Role.STUDENT,
            course_name='Bachelor of Science in Information Technology',
            course_code='IT'
        )
        self.ctype = CredentialType.objects.create(
            code='TOR', name='Transcript', price=Decimal('150.00'), processing_days=5
        )

    def test_default_status_assignment(self):
        request = CredentialRequest.objects.create(
            user=self.student,
            credential_type=self.ctype
        )
        self.assertEqual(request.status, RequestStatus.PENDING)

    def test_tracking_number_generation_format(self):
        request = CredentialRequest.objects.create(
            user=self.student,
            credential_type=self.ctype
        )
        date_str = timezone.now().strftime('%y-%m-%d')
        expected_tracking = f'IT-{date_str}-233206967-1-001'
        self.assertEqual(request.tracking_number, expected_tracking)
        self.assertEqual(request.course, 'IT')

    def test_tracking_number_uniqueness_and_increment(self):
        request1 = CredentialRequest.objects.create(
            user=self.student,
            credential_type=self.ctype
        )
        request2 = CredentialRequest.objects.create(
            user=self.student,
            credential_type=self.ctype
        )
        self.assertNotEqual(request1.tracking_number, request2.tracking_number)

        seq1 = int(request1.tracking_number.split('-')[-1])
        seq2 = int(request2.tracking_number.split('-')[-1])
        self.assertEqual(seq1, 1)
        self.assertEqual(seq2, 2)

    def test_tracking_number_multi_doc_combination(self):
        request = CredentialRequest(
            user=self.student,
            credential_type=self.ctype
        )
        request._custom_doc_code = '12'
        request.save()
        date_str = timezone.now().strftime('%y-%m-%d')
        self.assertEqual(request.tracking_number, f'IT-{date_str}-233206967-12-001')

    def test_credential_type_relationship(self):
        request = CredentialRequest.objects.create(
            user=self.student,
            credential_type=self.ctype
        )
        self.assertEqual(request.credential_type.code, 'TOR')
        self.assertEqual(request.user.username, '20233206967')

    def test_request_status_enum_integrity(self):
        request = CredentialRequest.objects.create(
            user=self.student,
            credential_type=self.ctype,
            status=RequestStatus.PROCESSING
        )
        self.assertEqual(request.status, 'PROCESSING')

        choices = [choice[0] for choice in RequestStatus.choices]
        self.assertIn(RequestStatus.PROCESSING, choices)
