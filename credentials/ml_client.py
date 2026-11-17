"""
RegQuest ML Microservice Client Service Layer.
Manages secure, fault-tolerant HTTP communication between Django backend and
FastAPI ML microservice.
Guarantees graceful degradation: if ML microservice is unavailable, fallback
business logic engages.
"""

import json
import logging
import math
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from .models import CredentialType

logger = logging.getLogger(__name__)

ML_BASE_URL = getattr(settings, 'ML_SERVICE_URL', 'http://localhost:8001').rstrip('/')


class MLClient:
    """Client wrapper for RegQuest FastAPI ML microservice."""

    @staticmethod
    def _post(endpoint: str, payload: dict, timeout: float = 2.5) -> dict:
        url = f"{ML_BASE_URL}{endpoint}"
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            url,
            data=data,
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                if response.status == 200:
                    return json.loads(response.read().decode('utf-8'))
        except (
            urllib.error.URLError, urllib.error.HTTPError, TimeoutError, Exception
        ) as e:
            logger.warning(f"ML Service call to {endpoint} failed: {e}")
            return None

    @staticmethod
    def _get(endpoint: str, timeout: float = 2.0) -> dict:
        url = f"{ML_BASE_URL}{endpoint}"
        req = urllib.request.Request(
            url,
            headers={'Content-Type': 'application/json'},
            method='GET'
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                if response.status == 200:
                    return json.loads(response.read().decode('utf-8'))
        except Exception as e:
            logger.warning(f"ML Service GET {endpoint} failed: {e}")
            return None

    @classmethod
    def get_health(cls) -> dict:
        res = cls._get("/health")
        if res:
            return res
        return {
            "status": "unavailable",
            "model_availability": {
                "daily_forecaster": False,
                "processing_baseline": False
            },
            "detail": "ML microservice is currently unreachable."
        }

    @staticmethod
    def _add_operating_days(start_date_str: str, operating_days: float) -> str:
        """
        Adds operating days (Mon-Fri) to start_date_str (or today) and
        returns an ISO YYYY-MM-DD estimated completion date.
        """
        base_date = timezone.localdate()
        if start_date_str:
            try:
                base_date = datetime.strptime(
                    str(start_date_str)[:10], "%Y-%m-%d"
                ).date()
            except ValueError:
                base_date = timezone.localdate()

        days_to_add = max(1, int(math.ceil(float(operating_days or 1))))
        current = base_date
        added = 0
        while added < days_to_add:
            current += timedelta(days=1)
            if current.weekday() < 5:  # Mon=0 .. Fri=4
                added += 1
        return current.isoformat()

    @classmethod
    def predict_processing_time(
        cls,
        credential_code: str,
        purpose: str = "Employment",
        date_requested: str = None,
        num_documents: int = 1
    ) -> dict:
        """
        Estimates processing turnaround time in operating days.
        Falls back to CredentialType database master data if ML microservice
        is unreachable. Always includes estimated_completion_date (YYYY-MM-DD).
        """
        payload = {
            "credential_type": credential_code,
            "purpose": purpose or "Employment",
            "date_requested": date_requested,
            "num_documents": num_documents or 1
        }
        res = cls._post("/predict/processing-time", payload, timeout=2.0)
        if res and res.get("status") == "success":
            res["is_fallback"] = False
            if not res.get("estimated_completion_date"):
                pred_days = res.get("predicted_processing_time", 3.0)
                res["estimated_completion_date"] = cls._add_operating_days(
                    date_requested, pred_days
                )
            return res

        # Graceful fallback: query CredentialType from database
        raw_code = str(credential_code or '').strip()
        ctype = (
            CredentialType.objects.filter(
                Q(code__iexact=raw_code)
                | Q(doc_code__iexact=raw_code)
                | Q(name__icontains=raw_code)
            ).first()
            if raw_code
            else None
        )
        base_days = float(ctype.processing_days) if ctype else 3.0
        fallback_days = base_days + (0.5 if num_documents > 1 else 0.0)
        est_date = cls._add_operating_days(date_requested, fallback_days)

        return {
            "status": "success",
            "predicted_processing_time": fallback_days,
            "estimated_completion_date": est_date,
            "unit": "operating_days",
            "model_version": "database-fallback-v1",
            "basis": "database_credential_type",
            "is_empirical": False,
            "is_fallback": True,
            "disclaimer": (
                "ML microservice unreachable; estimated processing duration derived "
                "from registrar master configuration."
            )
        }

    @classmethod
    def forecast_daily_demand(cls, start_date: str, operating_days: int = 20) -> dict:
        """
        Retrieves daily incoming request forecast for upcoming operating days.
        """
        payload = {
            "start_date": start_date,
            "number_of_operating_days": operating_days
        }
        res = cls._post("/forecast/daily", payload, timeout=3.0)
        if res and res.get("status") == "success":
            return res

        return {
            "status": "unavailable",
            "detail": "Daily demand forecasting service is currently unavailable.",
            "forecast": []
        }

    @classmethod
    def forecast_monthly_workload(cls, target_month: str = None) -> dict:
        """
        Retrieves monthly workload volume forecast and operational classification.
        """
        payload = {}
        if target_month:
            payload["target_month"] = target_month

        res = cls._post("/forecast/monthly-workload", payload, timeout=3.0)
        if res and res.get("status") == "success":
            return res

        return {
            "status": "unavailable",
            "detail": "Monthly workload forecasting service is currently unavailable."
        }
