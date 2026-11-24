"""
RegQuest ML Microservice Client Service Layer.
Manages secure, fault-tolerant HTTP communication between Django backend and
FastAPI ML microservice.
Guarantees graceful degradation: if ML microservice is unavailable, fallback
business logic engages.
"""

import json
import logging
import urllib.request
import urllib.error
from django.conf import settings

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
                "daily_forecaster": False
            },
            "detail": "ML microservice is currently unreachable."
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
