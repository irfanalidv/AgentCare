"""
Book into an EHR through the FHIR connector (against a local stand-in server)
============================================================================
Shows    : ``FHIRAppointmentConnector`` searching free ``Slot`` resources and creating
           an ``Appointment`` that references the chosen slot. A tiny FHIR-shaped HTTP
           server runs on localhost in a background thread so the example is
           self-contained; point ``base_url`` at a real FHIR R4 server (HAPI, Medplum,
           a vendor sandbox) to use it for real, or set APPOINTMENT_CONNECTOR_BACKEND=fhir
           and FHIR_BASE_URL so the front-desk pipeline picks it up automatically.
Needs    : ``pip install agentcare``. No API keys; binds a random localhost port.
Run      : python examples/fhir_booking_local_server.py
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from agentcare.connectors.appointments import FHIRAppointmentConnector

SLOTS = {
    "resourceType": "Bundle",
    "type": "searchset",
    "entry": [
        {
            "resource": {
                "resourceType": "Slot",
                "id": "slot-b",
                "status": "free",
                "start": "2026-11-03T10:30:00Z",
                "end": "2026-11-03T11:00:00Z",
            }
        },
        {
            "resource": {
                "resourceType": "Slot",
                "id": "slot-a",
                "status": "free",
                "start": "2026-11-03T10:00:00Z",
                "end": "2026-11-03T10:30:00Z",
            }
        },
    ],
}
created: list[dict] = []


class FakeFHIR(BaseHTTPRequestHandler):
    def _send(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/fhir+json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        self._send(200 if self.path.startswith("/fhir/Slot") else 404, SLOTS)

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        created.append(body)
        self._send(201, {**body, "id": f"appt-{len(created)}"})

    def log_message(self, *args) -> None:  # keep the example output clean
        pass


server = HTTPServer(("127.0.0.1", 0), FakeFHIR)
threading.Thread(target=server.serve_forever, daemon=True).start()
base_url = f"http://127.0.0.1:{server.server_port}/fhir"

connector = FHIRAppointmentConnector(base_url=base_url, schedule_id="sched-ortho", timeout_sec=5)
check = connector.check_slots(preferred_date_or_window="2026-11-03", execution_id="call-001")
print("free slots:", check.slots_preview)
print("chosen    :", check.chosen_start_iso)

booking = connector.book_slot(
    patient_name="Ava Patel",
    patient_email="ava@example.com",
    patient_phone="+15550001001",
    reason="knee pain follow-up",
    doctor_name="Dr. Rahul Verma",
    doctor_specialty="Orthopedics",
    visit_type="follow_up",
    summary=None,
    preferred_date_or_window="2026-11-03",
    slot_start_iso=None,  # let the connector pick the earliest free slot
    execution_id="call-001",
)
print("booking   :", booking)
print(
    "appointment sent to EHR:",
    json.dumps({k: created[0][k] for k in ("status", "start", "end", "slot")}, indent=2),
)
server.shutdown()
