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
            username='stud1', email='s@test.com', password='p', role=Role.STUDENT
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
        year = timezone.now().year
        self.assertTrue(request.tracking_number.startswith(f'REQ-{year}-'))
        self.assertEqual(len(request.tracking_number), 15)

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
        self.assertEqual(seq2, seq1 + 1)

    def test_credential_type_relationship(self):
        request = CredentialRequest.objects.create(
            user=self.student,
            credential_type=self.ctype
        )
        self.assertEqual(request.credential_type.code, 'TOR')
        self.assertEqual(request.user.username, 'stud1')

    def test_request_status_enum_integrity(self):
        request = CredentialRequest.objects.create(
            user=self.student,
            credential_type=self.ctype,
            status=RequestStatus.PROCESSING
        )
        self.assertEqual(request.status, 'PROCESSING')

        choices = [choice[0] for choice in RequestStatus.choices]
        self.assertIn(RequestStatus.PROCESSING, choices)
