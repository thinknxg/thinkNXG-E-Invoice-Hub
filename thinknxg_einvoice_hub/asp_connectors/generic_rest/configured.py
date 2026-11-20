"""ASP adapter driven by an "ASP REST API Configuration" record.

This is how an ordinary REST-based provider is onboarded without code: the
administrator describes authentication, endpoints, headers, request and response
mappings and webhooks in the UI, and this adapter runs them through
``ASPRestEngine``. Dedicated provider adapters subclass it and override only what
is unusual about their API.

The adapter's capabilities are not fixed: they follow the operations that are
actually configured and enabled.
"""

import base64

from thinknxg_einvoice_hub.asp_connectors import base_adapter as b
from thinknxg_einvoice_hub.exceptions import NotSupportedError, PermanentError
from thinknxg_einvoice_hub.services.asp_rest_engine import (
	DELIVERY_STATES,
	FTA_STATES,
	SUBMISSION_STATES,
	ASPRestEngine,
	_state,
)
from thinknxg_einvoice_hub.utils import get_path, loads
from thinknxg_einvoice_hub.webhook_security import verify_configured, verify_signature

OPERATION_CAPABILITIES = {
	"Submit Invoice": b.CAP_SUBMIT,
	"Get Invoice Status": b.CAP_STATUS,
	"Verify Credentials": b.CAP_VERIFY,
	"Get Participant": b.CAP_PARTICIPANT,
	"Validate Invoice": b.CAP_VALIDATE,
	"Submit Credit Note": b.CAP_CREDIT_NOTE,
	"Submit Self-Billed Invoice": b.CAP_SELF_BILLING,
	"Get Reporting Status": b.CAP_REPORTING_STATUS,
	"Get Delivery Status": b.CAP_DELIVERY_STATUS,
	"Download XML": b.CAP_XML,
	"Download PDF": b.CAP_PDF,
	"Register Webhook": b.CAP_REGISTER_WEBHOOK,
	"Get Incoming Invoices": b.CAP_INCOMING,
}


class ConfiguredRestAdapter(b.BaseASPConnector):
	code = "rest_config"
	label = "Configurable REST API (UI)"
	status = "Available"
	description = ("Runs any provider described by an ASP REST API Configuration. Capabilities follow the "
		"operations configured there.")
	capabilities = frozenset()

	def __init__(self, connection):
		super().__init__(connection)
		self.rest = self.connection.get("rest") or {}
		self._transaction = None
		logger = self.connection.get("logger")
		self.engine = ASPRestEngine(
			token_store=self.connection.get("token_store"),
			logger=(lambda entry: logger({**entry, "transaction": self._transaction})) if logger else None,
		)
		caps = {cap for op, cap in OPERATION_CAPABILITIES.items() if self.engine.has_operation(self.rest, op)}
		webhook = self.rest.get("webhook") or {}
		if webhook.get("enabled"):
			caps.update({b.CAP_WEBHOOKS, b.CAP_INBOUND})
		if b.CAP_INCOMING in caps:
			caps.add(b.CAP_INBOUND)
		self.capabilities = frozenset(caps)

	# -- helpers -----------------------------------------------------------
	def _require_configuration(self):
		if not self.rest:
			raise PermanentError(
				f"ASP connection {self.connection.get('name')} has no ASP REST API Configuration attached"
			)

	def _context(self, payload=None, metadata=None):
		metadata = dict(metadata or {})
		invoice = metadata.pop("_canonical", None)
		self._transaction = metadata.get("transaction")
		text = payload if isinstance(payload, str) else None
		return {
			"invoice": invoice or {},
			"document": text,
			"document_base64": base64.b64encode(text.encode("utf-8")).decode() if text else None,
			"metadata": metadata,
			"idempotency_key": metadata.get("idempotency_key") or metadata.get("transaction"),
			"environment": self.rest.get("environment"),
			"participant": self.rest.get("participant") or {},
		}

	def _params(self, metadata=None, **extra):
		params = {k: v for k, v in (self.rest.get("participant") or {}).items() if v not in (None, "")}
		params.update({k: v for k, v in (metadata or {}).items() if isinstance(v, (str, int)) and not k.startswith("_")})
		params.update({k: v for k, v in extra.items() if v not in (None, "")})
		return params

	def _run(self, operation, payload=None, metadata=None, **path_params):
		self._require_configuration()
		return self.engine.execute(self.rest, operation, payload, self._context(payload, metadata),
			self._params(metadata, **path_params))

	def _result(self, response, reference=None, default_status=None):
		mapped = response.get("mapped") or {}
		status = mapped.get("submission_status") or default_status
		if mapped.get("success") is False:
			status = b.ST_REJECTED
		extra = {k: mapped.get(k) for k in ("fta_status", "fta_reference", "delivery_status", "delivery_reference",
			"submission_reference", "error_code", "xml_url", "pdf_url", "timestamp", "invoice_mls_code", "tdd_mls_code")}
		return b.result(status, mapped.get("asp_document_id") or reference, mapped.get("error_message"),
			response.get("data") if not isinstance(response.get("data"), bytes) else None, **extra)

	# -- contract ----------------------------------------------------------
	def authenticate(self):
		self._require_configuration()
		return bool(self.engine.authenticate(self.rest)) or (self.rest.get("auth") or {}).get("type") in (None, "None")

	def verify_credentials(self):
		self._require_configuration()
		if self.engine.has_operation(self.rest, "Verify Credentials"):
			self._run("Verify Credentials")
			return "Credentials verified with the provider"
		if ((self.rest.get("auth") or {}).get("type") or "").startswith("OAuth2"):
			self.engine.refresh_token(self.rest)
			return "Access token obtained from the provider"
		self.engine.authenticate(self.rest)
		return "Configuration is complete; no Verify Credentials endpoint is configured to test it remotely"

	def test_connection(self):
		return self.verify_credentials()

	def _submit(self, operation, payload, metadata):
		if not self.engine.has_operation(self.rest, operation):
			operation = "Submit Invoice"  # many providers take every document type on one endpoint
		response = self._run(operation, payload, metadata)
		outcome = self._result(response, default_status=b.ST_ACCEPTED)
		if not outcome["reference"] and outcome["status"] != b.ST_REJECTED:
			raise PermanentError("Provider response contained no document ID; check the response mapping for "
				"'asp_document_id'")
		return outcome

	def submit_document(self, payload, metadata):
		return self._submit("Submit Invoice", payload, metadata)

	def submit_invoice(self, payload, metadata):
		return self._submit("Submit Invoice", payload, metadata)

	def submit_credit_note(self, payload, metadata):
		return self._submit("Submit Credit Note", payload, metadata)

	def submit_self_billed_invoice(self, payload, metadata):
		return self._submit("Submit Self-Billed Invoice", payload, metadata)

	def validate_invoice(self, payload, metadata):
		response = self._run("Validate Invoice", payload, metadata)
		mapped = response.get("mapped") or {}
		return {"valid": mapped.get("success") is not False, "message": mapped.get("error_message"),
			"raw": response.get("data")}

	def get_document_status(self, reference):
		return self._result(self._run("Get Invoice Status", document_id=reference), reference)

	def get_reporting_status(self, reference):
		return self._result(self._run("Get Reporting Status", document_id=reference), reference)

	def get_delivery_status(self, reference):
		return self._result(self._run("Get Delivery Status", document_id=reference), reference)

	def _download(self, operation, reference, url_field):
		response = self._run(operation, document_id=reference)
		data = response.get("data")
		if isinstance(data, (dict, list)):
			link = (response.get("mapped") or {}).get(url_field)
			if not link:
				raise PermanentError(f"{operation}: response is JSON without a mapped '{url_field}'")
			# the link is fetched under the same host allow-list as every other call
			follow = {**self.rest, "endpoints": {operation: {"method": "GET", "url": link, "enabled": 1}},
				"request_mappings": [], "response_mappings": []}
			data = self.engine.execute(follow, operation)["data"]
		return data

	def get_document_xml(self, reference):
		return self._download("Download XML", reference, "xml_url")

	def get_document_pdf(self, reference):
		return self._download("Download PDF", reference, "pdf_url")

	def get_participant_details(self, participant_id=None):
		return self._run("Get Participant", participant_id=participant_id).get("data")

	def register_participant(self, details):
		return self._run("Register Participant", details).get("data")

	def register_webhook(self, url):
		context_payload = {"url": url}
		return self._run("Register Webhook", context_payload, {"webhook_url": url}).get("data")

	def get_incoming_invoices(self, since=None):
		data = self._run("Get Incoming Invoices", {"since": since} if since else None).get("data")
		if isinstance(data, dict):
			path = self.rest.get("incoming_list_path")
			data = get_path(data, path) if path else next(
				(data[k] for k in ("data", "items", "results", "documents") if isinstance(data.get(k), list)), [])
		return data if isinstance(data, list) else []

	def normalize_response(self, response):
		return self._result({"data": response, "mapped": self.engine.map_response(self.rest, response)})

	# -- inbound and webhooks ------------------------------------------------
	def receive_document(self, payload):
		if isinstance(payload, str):
			return {"content": payload, "format": "XML" if payload.lstrip().startswith("<") else "JSON"}
		webhook = self.rest.get("webhook") or {}
		document = get_path(payload, webhook.get("document_path") or "document")
		if document is None:
			raise PermanentError("Inbound payload does not contain a document at the configured path")
		if isinstance(document, str) and webhook.get("document_base64"):
			document = base64.b64decode(document).decode("utf-8")
		fmt = "XML" if isinstance(document, str) and document.lstrip().startswith("<") else "JSON"
		return {"content": document, "format": fmt}

	def verify_webhook(self, body, headers):
		webhook = self.rest.get("webhook") or {}
		# the secret on the tenant's own connection wins over the default stored with the API configuration
		secret = self.connection.get("webhook_secret") or webhook.get("secret")
		if webhook.get("enabled"):
			return verify_configured({**webhook, "secret": secret}, body, headers)
		return verify_signature(secret, body, headers)

	def parse_webhook(self, payload):
		return self.process_webhook(payload)

	def process_webhook(self, payload, headers=None):
		webhook = self.rest.get("webhook") or {}
		payload = payload if isinstance(payload, dict) else {}
		event_type = get_path(payload, webhook.get("event_type_path") or "event")
		event_id = get_path(payload, webhook.get("event_id_path") or "id")
		reference = get_path(payload, webhook.get("document_id_path") or "document_id")
		document_events = [e.strip() for e in str(webhook.get("document_events") or "").split(",") if e.strip()]
		if event_type in document_events:
			return {"kind": "document", "payload": payload, "reference": str(reference) if reference else None,
				"event_id": event_id, "event_type": event_type}
		extra = {}
		for field, path in (loads(webhook.get("payload_mapping"), {}) or {}).items():
			extra[field] = get_path(payload, path)
		status = _state(get_path(payload, webhook.get("status_path") or "status"), SUBMISSION_STATES)
		if "fta_status" in extra:
			extra["fta_status"] = _state(extra["fta_status"], FTA_STATES)
		if "delivery_status" in extra:
			extra["delivery_status"] = _state(extra["delivery_status"], DELIVERY_STATES)
		message = extra.pop("error_message", None)
		return {"kind": "status", "event_id": event_id, "event_type": event_type,
			**b.result(status, str(reference) if reference else None, message, payload, **extra)}


class ContractPendingAdapter(ConfiguredRestAdapter):
	"""Base for named providers whose API contract has not been verified yet.

	It behaves exactly like the configurable adapter, but refuses to run until an
	ASP REST API Configuration built from the provider's official documentation is
	attached, and says what is missing.
	"""

	status = "Development"
	provider_name = ""
	legal_name = ""
	accreditation_number = ""
	documentation_url = ""

	def require(self, capability):
		# say what is missing from the contract rather than a bare "not supported"
		self._require_configuration()
		super().require(capability)

	def _require_configuration(self):
		if not self.rest or not (self.rest.get("endpoints") or {}):
			raise NotSupportedError(
				f"{self.provider_name or self.label}: the API contract is not configured. Obtain the provider's "
				"official API documentation and sandbox credentials, then complete an ASP REST API Configuration "
				"for this connection."
			)
