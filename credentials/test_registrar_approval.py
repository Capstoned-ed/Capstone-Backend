from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status
from decimal import Decimal
from credentials.models import (
    CredentialType,
    RequestStatus,
    RegistrarSettings,
    StudentClearance,
    ClearanceStatus
)
from credentials.services import CredentialRequestService
from accounts.models import Role

User = get_user_model()


class RegistrarApprovalWorkflowTests(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.admin = User.objects.create_user(
            username='admin_user',
            password='Password123!',
            role=Role.ADMIN,
            first_name='Admin',
            last_name='Chief'
        )
        self.registrar = User.objects.create_user(
            username='registrar_user',
            password='Password123!',
            role=Role.REGISTRAR,
            first_name='Jonalin',
            last_name='Lagrada'
        )
        self.staff = User.objects.create_user(
            username='staff_user',
            password='Password123!',
            role=Role.STAFF,
            first_name='Maria',
            last_name='Santos'
        )
        self.student = User.objects.create_user(
            username='student_user',
            password='Password123!',
            role=Role.STUDENT,
            first_name='Juan',
            last_name='Dela Cruz'
        )

        self.cred_type = CredentialType.objects.create(
            code='TOR',
            doc_code='1',
            name='Transcript of Records',
            price=Decimal('150.00'),
            processing_days=3,
            is_active=True
        )

        self.clearance = StudentClearance.objects.create(
            user=self.student,
            status=ClearanceStatus.APPROVED,
            file='clearances/dummy.pdf'
        )

        self.settings = RegistrarSettings.get_settings()
        self.settings.auto_approve_requests = True
        self.settings.save()

    def test_get_and_patch_registrar_settings(self):
        # 1. Staff cannot modify approval settings
        self.client.force_authenticate(user=self.staff)
        res = self.client.patch('/api/settings/registrar-approval/', {
            'auto_approve_requests': False
        })
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # 2. Registrar can view settings
        self.client.force_authenticate(user=self.registrar)
        res = self.client.get('/api/settings/registrar-approval/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data['auto_approve_requests'])
        self.assertEqual(res.data['active_registrar_name'], 'Jonalin Lagrada')

        # 3. Registrar can toggle auto_approve_requests to False
        patch_res = self.client.patch('/api/settings/registrar-approval/', {
            'auto_approve_requests': False
        })
        self.assertEqual(patch_res.status_code, status.HTTP_200_OK)
        self.assertFalse(patch_res.data['auto_approve_requests'])

        # Verify DB persisted
        self.settings.refresh_from_db()
        self.assertFalse(self.settings.auto_approve_requests)

    def test_mode_a_auto_approve_on_automatically_approves_request(self):
        self.settings.auto_approve_requests = True
        self.settings.save()

        # Student creates request
        req = CredentialRequestService.create_request(
            actor=self.student,
            validated_data={'credential_type': self.cred_type}
        )
        self.assertEqual(req.status, RequestStatus.PENDING)
        self.assertFalse(req.is_approved)

        # Registrar transitions to PAYMENT_PENDING (Order of Payment confirmed)
        updated = CredentialRequestService.transition_request(
            actor=self.registrar,
            credential_request=req,
            new_status=RequestStatus.PAYMENT_PENDING
        )
        self.assertTrue(updated.is_approved)
        self.assertTrue(updated.is_auto_approved)
        self.assertEqual(updated.approved_by_name, 'Jonalin Lagrada')
        self.assertEqual(updated.approved_by, self.registrar)

        # Registrar verifies payment and moves to PROCESSING
        updated = CredentialRequestService.transition_request(
            actor=self.registrar,
            credential_request=updated,
            new_status=RequestStatus.PAYMENT_VERIFIED
        )
        updated = CredentialRequestService.transition_request(
            actor=self.staff,
            credential_request=updated,
            new_status=RequestStatus.PROCESSING
        )
        # Registrar transitions PROCESSING -> READY_FOR_RELEASE
        updated = CredentialRequestService.transition_request(
            actor=self.registrar,
            credential_request=updated,
            new_status=RequestStatus.READY_FOR_RELEASE
        )
        # Staff releases request
        final_req = CredentialRequestService.transition_request(
            actor=self.staff,
            credential_request=updated,
            new_status=RequestStatus.RELEASED
        )
        self.assertEqual(final_req.status, RequestStatus.RELEASED)
        self.assertTrue(final_req.is_approved)

    def test_mode_b_auto_approve_off_blocks_release_until_registrar_approves(self):
        # 1. Turn toggle OFF
        self.settings.auto_approve_requests = False
        self.settings.save()

        req = CredentialRequestService.create_request(
            actor=self.student,
            validated_data={'credential_type': self.cred_type}
        )

        # Registrar transitions to PAYMENT_PENDING and PAYMENT_VERIFIED
        req = CredentialRequestService.transition_request(
            actor=self.registrar,
            credential_request=req,
            new_status=RequestStatus.PAYMENT_PENDING
        )
        self.assertFalse(req.is_approved)
        self.assertEqual(req.approved_by_name, '')

        req = CredentialRequestService.transition_request(
            actor=self.registrar,
            credential_request=req,
            new_status=RequestStatus.PAYMENT_VERIFIED
        )
        req = CredentialRequestService.transition_request(
            actor=self.staff,
            credential_request=req,
            new_status=RequestStatus.PROCESSING
        )
        self.assertFalse(req.is_approved)

        # 2. Transitioning to READY_FOR_RELEASE is blocked without prior approval
        with self.assertRaises(Exception) as ctx:
            CredentialRequestService.transition_request(
                actor=self.registrar,
                credential_request=req,
                new_status=RequestStatus.READY_FOR_RELEASE
            )
        self.assertIn("Registrar approval", str(ctx.exception))

        # 3. Staff or Student cannot call approve endpoint
        self.client.force_authenticate(user=self.staff)
        res = self.client.post(f'/api/requests/{req.id}/approve/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # 4. Registrar calls approve endpoint -> succeeds!
        self.client.force_authenticate(user=self.registrar)
        res = self.client.post(f'/api/requests/{req.id}/approve/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data['is_approved'])
        self.assertFalse(res.data['is_auto_approved'])
        self.assertEqual(res.data['approved_by_name'], 'Jonalin Lagrada')

        # 5. Registrar can now transition to READY_FOR_RELEASE and Staff can release
        req.refresh_from_db()
        self.assertTrue(req.is_approved)
        req = CredentialRequestService.transition_request(
            actor=self.registrar,
            credential_request=req,
            new_status=RequestStatus.READY_FOR_RELEASE
        )
        self.assertEqual(req.status, RequestStatus.READY_FOR_RELEASE)

        req = CredentialRequestService.transition_request(
            actor=self.staff,
            credential_request=req,
            new_status=RequestStatus.RELEASED
        )
        self.assertEqual(req.status, RequestStatus.RELEASED)
