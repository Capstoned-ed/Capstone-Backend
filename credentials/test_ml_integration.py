"""
Django Integration & Security Tests for RegQuest ML Integration Layer.
Tests:
1. Student turnaround prediction access & graceful database fallback
2. Role-Based Access Control: Students forbidden from administrative forecasts
3. Staff & Admin permitted access to forecasting endpoints
4. Fault tolerance when ML microservice is unavailable
"""

from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from accounts.models import Role
from credentials.models import CredentialType
from credentials.ml_client import MLClient

User = get_user_model()


class MLIntegrationTests(APITestCase):

    def setUp(self):
        # Create roles
        self.student = User.objects.create_user(
            username="student_user",
            email="student@example.com",
            password="Password123!",
            role=Role.STUDENT
        )
        self.staff = User.objects.create_user(
            username="staff_user",
            email="staff@example.com",
            password="Password123!",
            role=Role.STAFF
        )
        self.admin = User.objects.create_user(
            username="admin_user",
            email="admin@example.com",
            password="Password123!",
            role=Role.ADMIN
        )

        # Create credential type in db
        self.tor_type = CredentialType.objects.create(
            code="TOR",
            name="Transcript of Records",
            price="150.00",
            processing_days=5,
            is_active=True
        )

        self.turnaround_url = reverse('predict-turnaround')
        self.daily_forecast_url = reverse('admin-daily-forecast')
        self.monthly_workload_url = reverse('admin-monthly-workload')
        self.health_url = reverse('ml-health-status')

    def test_student_can_predict_turnaround(self):
        self.client.force_authenticate(user=self.student)
        resp = self.client.get(self.turnaround_url, {'credential_type': 'TOR'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertGreater(data["predicted_processing_time"], 0)
        self.assertEqual(data["unit"], "operating_days")

    def test_turnaround_graceful_fallback_when_service_down(self):
        self.client.force_authenticate(user=self.student)
        # Mock _post to simulate network failure
        with patch.object(MLClient, '_post', return_value=None):
            resp = self.client.get(self.turnaround_url, {'credential_type': 'TOR'})
            self.assertEqual(resp.status_code, status.HTTP_200_OK)
            data = resp.json()
            self.assertEqual(data["status"], "success")
            self.assertTrue(data["is_fallback"])
            # Matches TOR's processing_days in DB (5)
            self.assertEqual(data["predicted_processing_time"], 5.0)

    def test_student_forbidden_from_daily_forecasting(self):
        self.client.force_authenticate(user=self.student)
        resp = self.client.get(self.daily_forecast_url)
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

        resp_post = self.client.post(self.daily_forecast_url, {"start_date": "2026-11-09"})
        self.assertEqual(resp_post.status_code, status.HTTP_403_FORBIDDEN)

    def test_student_forbidden_from_monthly_workload(self):
        self.client.force_authenticate(user=self.student)
        resp = self.client.get(self.monthly_workload_url)
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_permitted_daily_forecasting(self):
        self.client.force_authenticate(user=self.staff)
        mock_forecast = {
            "status": "success",
            "forecast": [{"date": "2026-11-09", "predicted_requests": 35}],
            "model_version": "daily-forecaster-ridge-v1"
        }
        with patch.object(MLClient, 'forecast_daily_demand', return_value=mock_forecast):
            resp = self.client.get(self.daily_forecast_url, {'start_date': '2026-11-09'})
            self.assertEqual(resp.status_code, status.HTTP_200_OK)
            self.assertEqual(resp.json()["status"], "success")

    def test_admin_permitted_monthly_workload(self):
        self.client.force_authenticate(user=self.admin)
        mock_workload = {
            "status": "success",
            "month": "2026-12",
            "predicted_total_requests": 400,
            "workload_level": "Light"
        }
        with patch.object(MLClient, 'forecast_monthly_workload', return_value=mock_workload):
            resp = self.client.get(self.monthly_workload_url, {'target_month': '2026-12'})
            self.assertEqual(resp.status_code, status.HTTP_200_OK)
            self.assertEqual(resp.json()["workload_level"], "Light")

    def test_ml_health_status_endpoint(self):
        self.client.force_authenticate(user=self.staff)
        mock_health = {
            "status": "ok",
            "model_availability": {"daily_forecaster": True, "processing_baseline": True}
        }
        with patch.object(MLClient, 'get_health', return_value=mock_health):
            resp = self.client.get(self.health_url)
            self.assertEqual(resp.status_code, status.HTTP_200_OK)
            self.assertEqual(resp.json()["status"], "ok")

