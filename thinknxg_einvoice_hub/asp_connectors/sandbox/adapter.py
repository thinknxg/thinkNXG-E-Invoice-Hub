"""Built-in sandbox ASP: a simulated provider for end-to-end testing.

No network calls are made and nothing is transmitted to any e-invoicing
network. Behaviour is driven by the invoice number so every path can be tested:

* contains ``REJECT``  -> the provider rejects the document
* contains ``TIMEOUT`` -> a temporary failure (exercises the retry engine)
* contains ``PENDING`` -> accepted, delivery confirmed later by status sync
* anything else        -> accepted and delivered
"""

from thinknxg_einvoice_hub.asp_connectors.base_adapter import (
	ALL_CAPABILITIES,
	ST_DELIVERED,
	ST_REJECTED,
	ST_SUBMITTED,
	BaseASPConnector,
	result,
)
from thinknxg_einvoice_hub.exceptions import PermanentError, TransientError
from thinknxg_einvoice_hub.utils import sha256


class SandboxAdapter(BaseASPConnector):
	code = "sandbox"
	label = "Sandbox (simulated ASP)"
	status = "Available"
	description = "Simulated provider for testing the full flow. Does not transmit anything."
	capabilities = frozenset(ALL_CAPABILITIES)

	def authenticate(self):
		return True

	def test_connection(self):
		return "Sandbox adapter ready (no external connection)"

	def submit_document(self, payload, metadata):
		if self.connection.get("environment") == "Production":
			raise PermanentError("The sandbox adapter cannot be used on a Production ASP connection")
		number = str((metadata or {}).get("invoice_number") or "").upper()
		if "TIMEOUT" in number:
			raise TransientError("Sandbox: simulated provider timeout")
		reference = "SBX-" + sha256(f"{number}:{payload}")[:16].upper()
		if "REJECT" in number:
			return self.normalize_response({"id": reference, "state": "rejected",
				"detail": "Sandbox: document rejected by simulated provider"})
		state = "accepted" if "PENDING" in number else "delivered"
		return self.normalize_response({"id": reference, "state": state, "detail": "Sandbox: simulated submission"})

	def get_document_status(self, reference):
		return self.normalize_response({"id": reference, "state": "delivered", "detail": "Sandbox: delivered"})

	def receive_document(self, payload):
		if isinstance(payload, dict):
			document = payload.get("document", payload)
			fmt = "XML" if isinstance(document, str) and document.lstrip().startswith("<") else "JSON"
			return {"content": document, "format": fmt}
		return {"content": payload, "format": "XML" if str(payload).lstrip().startswith("<") else "JSON"}

	def normalize_response(self, response):
		state = (response or {}).get("state")
		status = {"delivered": ST_DELIVERED, "rejected": ST_REJECTED}.get(state, ST_SUBMITTED)
		# the simulation also reports the two downstream outcomes so the full lifecycle can be exercised
		fta = {ST_DELIVERED: "REPORTED", ST_REJECTED: None}.get(status, "PENDING")
		delivery = {ST_DELIVERED: "DELIVERED", ST_REJECTED: None}.get(status, "PENDING")
		return result(status, response.get("id"), response.get("detail"), response, fta_status=fta,
			delivery_status=delivery)

	def parse_webhook(self, payload):
		payload = payload if isinstance(payload, dict) else {}
		if payload.get("document"):
			return {"kind": "document", "payload": payload}
		return {"kind": "status", **self.normalize_response(payload)}
