"""Universal ASP (Accredited Service Provider) adapter contract.

ASP adapters know nothing about ERPs. They receive the compliance document (or
canonical JSON) plus routing metadata and talk to one provider's API.

Every adapter reports results in one normalised shape::

    {"status": SUBMITTED | DELIVERED | REJECTED | PENDING | FAILED,
     "reference": "<provider document id>", "message": "...", "raw": <provider response>}
"""

from abc import ABC, abstractmethod

from thinknxg_einvoice_hub.exceptions import NotSupportedError
from thinknxg_einvoice_hub.http_client import HttpClient

ST_SUBMITTED = "SUBMITTED"
ST_ACCEPTED = "ACCEPTED"  # accepted by the ASP; FTA reporting and buyer delivery are tracked separately
ST_DELIVERED = "DELIVERED"
ST_REJECTED = "REJECTED"
ST_PENDING = "PENDING"
ST_FAILED = "FAILED"

CAP_SUBMIT = "submit"
CAP_STATUS = "status"
CAP_INBOUND = "inbound"
CAP_WEBHOOKS = "webhooks"
ALL_CAPABILITIES = (CAP_SUBMIT, CAP_STATUS, CAP_INBOUND, CAP_WEBHOOKS)
# optional operations; an ASP declares only what its API really offers
CAP_VERIFY = "verify_credentials"
CAP_PARTICIPANT = "participant"
CAP_VALIDATE = "validate"
CAP_CREDIT_NOTE = "credit_note"
CAP_SELF_BILLING = "self_billing"
CAP_REPORTING_STATUS = "reporting_status"
CAP_DELIVERY_STATUS = "delivery_status"
CAP_XML = "document_xml"
CAP_PDF = "document_pdf"
CAP_REGISTER_WEBHOOK = "register_webhook"
CAP_INCOMING = "incoming_invoices"
EXTENDED_CAPABILITIES = (CAP_VERIFY, CAP_PARTICIPANT, CAP_VALIDATE, CAP_CREDIT_NOTE, CAP_SELF_BILLING,
	CAP_REPORTING_STATUS, CAP_DELIVERY_STATUS, CAP_XML, CAP_PDF, CAP_REGISTER_WEBHOOK, CAP_INCOMING)

# FTA reporting and Peppol delivery outcomes, independent of the ASP's own acceptance
FTA_PENDING, FTA_REPORTED, FTA_REJECTED = "PENDING", "REPORTED", "REJECTED"
DLV_PENDING, DLV_DELIVERED, DLV_FAILED = "PENDING", "DELIVERED", "FAILED"


def result(status, reference=None, message=None, raw=None, **extra):
	"""Normalised adapter result.

	Optional ``extra`` keys: fta_status, fta_reference, fta_message, delivery_status,
	delivery_reference, delivery_message, submission_reference, error_code, xml_url, pdf_url, event_id.
	"""
	data = {"status": status, "reference": reference, "message": message, "raw": raw}
	data.update({k: v for k, v in extra.items() if v not in (None, "")})
	return data


class BaseASPConnector(ABC):
	code = ""
	label = ""
	status = "Planned"  # Available | Beta | Planned
	website = ""
	description = ""
	capabilities = frozenset()

	def __init__(self, connection):
		self.connection = connection or {}
		self.extra = self.connection.get("extra") or {}
		self.http = HttpClient(self.connection)

	def supports(self, capability):
		"""Instance-level check: configurable adapters derive capabilities from their configuration."""
		return capability in self.capabilities

	def require(self, capability):
		if not self.supports(capability):
			raise NotSupportedError(f"{self.label or self.code} adapter does not support '{capability}'")

	@abstractmethod
	def authenticate(self):
		"""Establish or verify credentials."""

	@abstractmethod
	def submit_document(self, payload, metadata):
		"""Submit a document. ``payload`` is a string (XML or JSON). Return a normalised result."""

	@abstractmethod
	def get_document_status(self, reference):
		"""Query the provider for the current status. Return a normalised result."""

	@abstractmethod
	def receive_document(self, payload):
		"""Extract an inbound document. Return ``{"content": str|dict, "format": "XML"|"JSON"}``."""

	@abstractmethod
	def normalize_response(self, response):
		"""Provider response -> normalised result dict."""

	@abstractmethod
	def test_connection(self):
		"""Return a short human-readable success message or raise."""

	def parse_webhook(self, payload):
		"""Interpret a provider webhook.

		Return ``{"kind": "status", ...normalised result}`` for status callbacks or
		``{"kind": "document", "payload": <payload for receive_document>}`` for inbound documents.
		"""
		raise NotSupportedError(f"{self.label or self.code} adapter does not handle webhooks")

	# -- extended contract (all optional; guarded by capabilities) --------------
	def _unsupported(self, what):
		raise NotSupportedError(f"{self.label or self.code} does not support {what}")

	def verify_credentials(self):
		return self.test_connection()

	def get_participant_details(self, participant_id=None):
		self._unsupported("participant lookup")

	def register_participant(self, details):
		self._unsupported("participant registration")

	def validate_invoice(self, payload, metadata):
		self._unsupported("remote invoice validation")

	def submit_invoice(self, payload, metadata):
		return self.submit_document(payload, metadata)

	def submit_credit_note(self, payload, metadata):
		return self.submit_document(payload, metadata)

	def submit_self_billed_invoice(self, payload, metadata):
		return self.submit_document(payload, metadata)

	def get_reporting_status(self, reference):
		self._unsupported("FTA reporting status queries")

	def get_delivery_status(self, reference):
		self._unsupported("delivery status queries")

	def get_document_xml(self, reference):
		self._unsupported("XML retrieval")

	def get_document_pdf(self, reference):
		self._unsupported("PDF retrieval")

	def register_webhook(self, url):
		self._unsupported("webhook registration")

	def get_incoming_invoices(self, since=None):
		self._unsupported("incoming invoice retrieval")

	def verify_webhook(self, body, headers):
		"""Authenticate a webhook request. Default: HMAC-SHA256 with the connection's webhook secret."""
		from thinknxg_einvoice_hub.webhook_security import verify_signature

		return verify_signature(self.connection.get("webhook_secret"), body, headers)

	def process_webhook(self, payload, headers=None):
		return self.parse_webhook(payload)


class PlannedASPAdapter(BaseASPConnector):
	"""Placeholder for provider adapters that need the provider's API onboarding.

	Each Accredited Service Provider publishes its own API to onboarded
	customers. Until a dedicated adapter is written against that documentation,
	connect the provider through the ``generic_rest`` adapter, which is driven
	entirely by configuration.
	"""

	status = "Planned"
	capabilities = frozenset()

	def _planned(self):
		raise NotSupportedError(
			f"The {self.label} adapter is not implemented yet. Configure the provider through the "
			"'generic_rest' adapter, or add a dedicated adapter once API documentation is available."
		)

	def authenticate(self):
		self._planned()

	def submit_document(self, payload, metadata):
		self._planned()

	def get_document_status(self, reference):
		self._planned()

	def receive_document(self, payload):
		self._planned()

	def normalize_response(self, response):
		self._planned()

	def test_connection(self):
		self._planned()
