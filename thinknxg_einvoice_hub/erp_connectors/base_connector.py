"""Universal ERP connector contract.

Every ERP connector subclasses ``BaseERPConnector``. Connectors are plain
Python: they receive a decrypted ``connection`` dict (see
``core.connections.connection_config``) and an optional mapping dict, and never
read the database themselves. That keeps them unit-testable and lets them run
in a separate worker process later.

Not every ERP exposes the same integration surface, so each connector
advertises its ``capabilities``; the hub checks them before calling a method.
"""

from abc import ABC, abstractmethod

from thinknxg_einvoice_hub.canonical.invoice_schema import is_canonical
from thinknxg_einvoice_hub.canonical.mapper import apply_mapping
from thinknxg_einvoice_hub.exceptions import MappingError, NotSupportedError
from thinknxg_einvoice_hub.http_client import HttpClient

CAP_FETCH_INVOICE = "fetch_invoice"
CAP_FETCH_PENDING = "fetch_pending"
CAP_WEBHOOKS = "webhooks"
CAP_PURCHASE_INVOICE = "create_purchase_invoice"
CAP_STATUS_UPDATE = "status_update"
ALL_CAPABILITIES = (CAP_FETCH_INVOICE, CAP_FETCH_PENDING, CAP_WEBHOOKS, CAP_PURCHASE_INVOICE, CAP_STATUS_UPDATE)


class BaseERPConnector(ABC):
	code = ""
	label = ""
	status = "Planned"  # Available | Beta | Planned
	integration_methods = ""
	description = ""
	capabilities = frozenset()

	def __init__(self, connection, mapping=None):
		self.connection = connection or {}
		self.extra = self.connection.get("extra") or {}
		self.mapping = mapping
		self.http = HttpClient(self.connection)

	# -- capability helpers ------------------------------------------------
	def supports(self, capability):
		return capability in self.capabilities

	def require(self, capability):
		if not self.supports(capability):
			raise NotSupportedError(f"{self.label or self.code} connector does not support '{capability}'")

	# -- contract ----------------------------------------------------------
	@abstractmethod
	def authenticate(self):
		"""Establish or verify credentials. Return a truthy value on success."""

	@abstractmethod
	def fetch_invoice(self, document_id):
		"""Return the ERP's raw invoice payload (dict) for one document."""

	@abstractmethod
	def fetch_pending_invoices(self, filters=None):
		"""Return a list of ERP document IDs that still need to be transmitted."""

	def normalize_invoice(self, invoice):
		"""ERP payload -> canonical invoice (un-normalised).

		Default behaviour: pass canonical payloads through, otherwise apply the
		Mapping Configuration attached to the connection. Connectors with a
		well-known document model override this with a built-in mapping.
		"""
		if is_canonical(invoice):
			return invoice
		if self.mapping and self.mapping.get("rules"):
			return apply_mapping(invoice, self.mapping)
		raise MappingError(
			f"{self.label or self.code}: payload is not a canonical invoice and no Mapping Configuration is "
			"attached to the ERP connection"
		)

	@abstractmethod
	def create_purchase_invoice(self, invoice):
		"""Create a draft purchase invoice from an inbound canonical invoice. Return the ERP document ID."""

	@abstractmethod
	def update_invoice_status(self, document_id, status, details=None):
		"""Write the e-invoicing status back to the originating ERP document."""

	@abstractmethod
	def test_connection(self):
		"""Return a short human-readable success message or raise."""

	# -- convenience contract built on the methods above -------------------------
	def fetch_sales_invoices(self, filters=None):
		"""Pull mode: raw payloads of pending sales invoices and credit notes."""
		self.require(CAP_FETCH_PENDING)
		return [self.fetch_invoice(document_id) for document_id in self.fetch_pending_invoices(filters)]

	def fetch_credit_notes(self, filters=None):
		"""Credit notes travel with sales documents unless a connector separates them."""
		return []

	def fetch_purchase_invoices(self, filters=None):
		raise NotSupportedError(f"{self.label or self.code} connector does not expose purchase invoices")

	def update_source_document(self, result):
		"""Write a processing result back: ``{"document_id", "status", ...details}``."""
		result = dict(result or {})
		return self.update_invoice_status(result.pop("document_id", None), result.pop("status", None), result)

	def parse_webhook(self, payload):
		"""Interpret an ERP webhook. Return ``{"event", "document_id", "invoice"}``.

		``invoice`` may be ``None`` when the webhook only carries an ID; the hub
		then calls ``fetch_invoice`` if the connector supports it.
		"""
		payload = payload if isinstance(payload, dict) else {}
		return {
			"event": payload.get("event") or "invoice.created",
			"document_id": payload.get("document_id") or payload.get("id"),
			"invoice": payload.get("invoice"),
		}


class PlannedERPConnector(BaseERPConnector):
	"""Placeholder for connectors on the roadmap.

	The connector appears in the catalogue with its intended integration method
	so that routing, mapping and tenancy can be configured, but every call
	raises ``NotSupportedError`` until the connector is implemented. Until
	then such an ERP can integrate through the Universal API (connector code
	``custom``) with a Mapping Configuration.
	"""

	status = "Planned"
	capabilities = frozenset()

	def _planned(self):
		raise NotSupportedError(
			f"The {self.label} connector is on the roadmap and not implemented yet. Use the Universal API "
			"('custom' connector) with a Mapping Configuration to integrate this ERP today."
		)

	def authenticate(self):
		self._planned()

	def fetch_invoice(self, document_id):
		self._planned()

	def fetch_pending_invoices(self, filters=None):
		self._planned()

	def create_purchase_invoice(self, invoice):
		self._planned()

	def update_invoice_status(self, document_id, status, details=None):
		self._planned()

	def test_connection(self):
		self._planned()
