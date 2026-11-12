"""Configuration-driven REST adapter for any ASP with a JSON/XML HTTP API.

Use it to connect a provider before a dedicated adapter exists. All endpoint
paths and response field locations come from ``extra_config`` on the ASP
Connection (values shown are the defaults)::

    {
      "submit_path": "/documents",
      "submit_mode": "envelope",          # envelope: JSON {document, format, metadata}; raw: document as body
      "document_field": "document",       # envelope key holding the document
      "base64_document": false,           # base64-encode the document inside the envelope
      "status_path": "/documents/{reference}",
      "test_path": null,                  # GET endpoint used by Test Connection
      "reference_path": "id",             # where the provider's document ID sits in responses
      "state_path": "status",
      "message_path": "message",
      "status_map": {"accepted": "SUBMITTED", "delivered": "DELIVERED", "rejected": "REJECTED",
                     "pending": "PENDING", "failed": "FAILED"},
      "inbound_document_path": "document",    # webhook / inbound payload location of the document
      "inbound_base64": false,
      "inbound_fetch_path": null,             # e.g. "/inbox/{reference}/content" when webhooks carry only an ID
      "webhook_event_path": "event",
      "webhook_document_events": ["document.received"]
    }
"""

import base64
import json

from thinknxg_einvoice_hub.asp_connectors.base_adapter import (
	ALL_CAPABILITIES,
	ST_PENDING,
	ST_SUBMITTED,
	BaseASPConnector,
	result,
)
from thinknxg_einvoice_hub.exceptions import PermanentError
from thinknxg_einvoice_hub.utils import get_path

DEFAULT_STATUS_MAP = {
	"accepted": "SUBMITTED", "submitted": "SUBMITTED", "sent": "SUBMITTED", "processing": "PENDING",
	"pending": "PENDING", "queued": "PENDING", "delivered": "DELIVERED", "completed": "DELIVERED",
	"rejected": "REJECTED", "invalid": "REJECTED", "failed": "FAILED", "error": "FAILED",
}


class GenericRestAdapter(BaseASPConnector):
	code = "generic_rest"
	label = "Generic REST ASP"
	status = "Available"
	description = "Configuration-driven adapter for any provider with an HTTP API."
	capabilities = frozenset(ALL_CAPABILITIES)

	def _opt(self, key, default=None):
		val = self.extra.get(key)
		return default if val in (None, "") else val

	def authenticate(self):
		return bool(self.http.auth_headers()) or (self.connection.get("auth_type") or "None") == "None"

	def test_connection(self):
		self.authenticate()
		if self._opt("test_path"):
			self.http.request("GET", self._opt("test_path"))
			return "Connected"
		return "Credentials accepted locally; set test_path in Extra Configuration to verify against the provider"

	def submit_document(self, payload, metadata):
		metadata = metadata or {}
		path = self._opt("submit_path", "/documents")
		if self._opt("submit_mode", "envelope") == "raw":
			media = "application/xml" if metadata.get("format") == "XML" else "application/json"
			response = self.http.json("POST", path, data=payload.encode("utf-8"), headers={"Content-Type": media})
		else:
			document = payload
			if self._opt("base64_document", False):
				document = base64.b64encode(payload.encode("utf-8")).decode()
			body = {self._opt("document_field", "document"): document, "format": metadata.get("format"),
				"metadata": {k: v for k, v in metadata.items() if not k.startswith("_")}}
			response = self.http.json("POST", path, json=body)
		normalised = self.normalize_response(response)
		if not normalised["reference"]:
			raise PermanentError("Provider response did not contain a document reference "
				f"(looked at '{self._opt('reference_path', 'id')}')")
		return normalised

	def get_document_status(self, reference):
		path = self._opt("status_path", "/documents/{reference}").format(reference=reference)
		normalised = self.normalize_response(self.http.json("GET", path))
		normalised["reference"] = normalised["reference"] or reference
		return normalised

	def normalize_response(self, response):
		response = response if isinstance(response, dict) else {}
		state = get_path(response, self._opt("state_path", "status"))
		table = dict(DEFAULT_STATUS_MAP)
		table.update({str(k).lower(): v for k, v in (self._opt("status_map", {}) or {}).items()})
		status = table.get(str(state).lower(), ST_SUBMITTED if state is None else ST_PENDING)
		message = get_path(response, self._opt("message_path", "message"))
		reference = get_path(response, self._opt("reference_path", "id"))
		return result(status, str(reference) if reference not in (None, "") else None,
			message if isinstance(message, str) or message is None else json.dumps(message), response)

	def receive_document(self, payload):
		if isinstance(payload, str):
			return {"content": payload, "format": "XML" if payload.lstrip().startswith("<") else "JSON"}
		document = get_path(payload, self._opt("inbound_document_path", "document"))
		if document is None and self._opt("inbound_fetch_path"):
			reference = get_path(payload, self._opt("reference_path", "id"))
			document = self.http.request("GET", self._opt("inbound_fetch_path").format(reference=reference)).text
		if document is None:
			raise PermanentError("Inbound payload does not contain a document")
		if isinstance(document, str) and self._opt("inbound_base64", False):
			document = base64.b64decode(document).decode("utf-8")
		fmt = "XML" if isinstance(document, str) and document.lstrip().startswith("<") else "JSON"
		return {"content": document, "format": fmt}

	def parse_webhook(self, payload):
		payload = payload if isinstance(payload, dict) else {}
		event = get_path(payload, self._opt("webhook_event_path", "event"))
		if event in (self._opt("webhook_document_events", ["document.received"]) or []):
			return {"kind": "document", "payload": payload}
		return {"kind": "status", **self.normalize_response(payload)}
