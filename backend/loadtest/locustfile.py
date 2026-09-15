"""
Locust load-test script for the CLARION FastAPI backend.

This simulates realistic peak concurrent load for CLARION's ~23k-user
two-campus deployment (see healthcare/On-Prem Architecture.md and
healthcare/Implementation Roadmap.md P5.2) — NOT a literal 23k-concurrent-connection
test; real peak concurrency for a clinic this size (~150 encounters/day) is
estimated in the low hundreds.

Example run:
    locust -f backend/loadtest/locustfile.py --host http://localhost:8000 --headless -u 300 -r 20 -t 3m --csv=results/run1
"""
import logging
import random
from datetime import date, timedelta

from locust import HttpUser, between, task

logger = logging.getLogger(__name__)

# The one demo facility every seeded account belongs to (backend/seed.py).
# /patients/announcements, /booking-options and /appointment-slots all
# require facility_name as a query param -- confirmed against the real
# route signatures in routers/patients.py (422 "Field required" without it,
# caught live in the first real load-test run).
_FACILITY = "Hospital Sejahtera"


class _BaseClarionUser(HttpUser):
    """Abstract base user managing demo-account authentication and common setup."""

    abstract = True
    wait_time = between(1, 4)
    EMAIL: str = ""
    PASSWORD: str = ""

    def on_start(self):
        response = self.client.post(
            "/auth/login",
            data={"username": self.EMAIL, "password": self.PASSWORD},
            name="/auth/login",
        )
        if response.status_code == 200:
            token_data = response.json()
            access_token = token_data.get("access_token")
            if access_token:
                self.client.headers["Authorization"] = f"Bearer {access_token}"
        else:
            logger.error(
                "Login failed for %s: status_code=%s body=%s",
                self.EMAIL,
                response.status_code,
                response.text,
            )


class ReceptionistUser(_BaseClarionUser):
    weight = 3
    EMAIL = "receptionist@clarion.demo"
    PASSWORD = "receptionist123"

    @task(5)
    def queue(self):
        self.client.get("/reception/queue", name="/reception/queue")

    @task(2)
    def sections(self):
        self.client.get("/reception/sections", name="/reception/sections")

    @task(1)
    def checkin(self):
        # Synthetic load-test checkin payload using a plausible fake IC.
        # Exactly one identifier (national_id) is provided to satisfy ReceptionCheckinRequest.
        payload = {
            "national_id": f"900101-14-{random.randint(1000, 9999)}",
            "reason": "Load test checkin",
            "department": None,
        }
        with self.client.post(
            "/reception/checkin",
            json=payload,
            name="/reception/checkin",
            catch_response=True,
        ) as response:
            # 2xx and 4xx (e.g. 404 Patient not found) represent expected business outcomes.
            # Only 5xx or network transport errors count as load test failures.
            if response.status_code < 500:
                response.success()


class ClinicianUser(_BaseClarionUser):
    weight = 2
    EMAIL = "clinician@clarion.demo"
    PASSWORD = "clinician123"

    @task(4)
    def rooms(self):
        self.client.get("/consultation/rooms", name="/consultation/rooms")

    @task(3)
    def my_room(self):
        self.client.get("/consultation/my-room", name="/consultation/my-room")

    @task(2)
    def patients(self):
        self.client.get("/patients", params={"limit": 25}, name="/patients")

    @task(2)
    def dashboard_summary(self):
        self.client.get("/dashboard/summary", name="/dashboard/summary")

    @task(1)
    def flow_forecast(self):
        self.client.get("/dashboard/flow-forecast", name="/dashboard/flow-forecast")


class PharmacistUser(_BaseClarionUser):
    weight = 1
    EMAIL = "pharmacist@clarion.demo"
    PASSWORD = "pharmacist123"

    @task(4)
    def inventory(self):
        self.client.get("/pharmacy/inventory", name="/pharmacy/inventory")

    @task(2)
    def inventory_low_stock(self):
        self.client.get("/pharmacy/inventory/low-stock", name="/pharmacy/inventory/low-stock")

    @task(2)
    def summary(self):
        self.client.get("/pharmacy/summary", name="/pharmacy/summary")

    @task(1)
    def purchase_proposals(self):
        self.client.get("/pharmacy/purchase-proposals", name="/pharmacy/purchase-proposals")


class AdminUser(_BaseClarionUser):
    weight = 1
    EMAIL = "admin@clarion.demo"
    PASSWORD = "admin123"

    @task(3)
    def dashboard_summary(self):
        self.client.get("/dashboard/summary", name="/dashboard/summary")

    @task(2)
    def flow_forecast(self):
        self.client.get("/dashboard/flow-forecast", name="/dashboard/flow-forecast")

    @task(1)
    def predictive_visit_volume(self):
        self.client.get("/reports/predictive/visit-volume", name="/reports/predictive/visit-volume")

    @task(1)
    def predictive_risk_stratification(self):
        self.client.get("/reports/predictive/risk-stratification", name="/reports/predictive/risk-stratification")


class PatientUser(_BaseClarionUser):
    weight = 6
    EMAIL = "patient@clarion.demo"
    PASSWORD = "patient123"

    @task(5)
    def announcements(self):
        self.client.get(
            "/patients/announcements", params={"facility_name": _FACILITY}, name="/patients/announcements",
        )

    @task(3)
    def booking_options(self):
        self.client.get(
            "/patients/booking-options", params={"facility_name": _FACILITY}, name="/patients/booking-options",
        )

    @task(2)
    def appointment_slots(self):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        self.client.get(
            "/patients/appointment-slots",
            params={"facility_name": _FACILITY, "date": tomorrow},
            name="/patients/appointment-slots",
        )
