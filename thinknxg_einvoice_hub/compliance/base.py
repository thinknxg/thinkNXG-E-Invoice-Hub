"""Country compliance engine contract.

A compliance engine turns a canonical invoice into the document a network or
tax authority expects, and back again for inbound documents. Engines are pure
Python: they receive a plain ``profile`` dict and never touch the database.

Each country has its own engine (``compliance/uae``, ``compliance/oman``, ...).
Engines share the canonical model, the XML helpers and the processing pipeline,
but never each other's rules: UAE and Oman differ in identifiers, tax rules,
decimals and transaction-type coding even though both use Peppol PINT.
"""

from abc import ABC, abstractmethod

#: lifecycle values understood by the processing engine (see services/invoice_service.py)
GENERIC_STATUS = {
	"accepted": "ACCEPTED", "valid": "ACCEPTED", "cleared": "ACCEPTED", "success": "ACCEPTED",
	"rejected": "REJECTED", "invalid": "REJECTED", "failed": "REJECTED", "error": "REJECTED",
	"pending": "PENDING", "queued": "PENDING", "processing": "PENDING", "submitted": "PENDING",
	"reported": "REPORTED", "delivered": "DELIVERED",
}


class BaseComplianceEngine(ABC):
	code = ""
	label = ""
	country = ""
	country_code = ""
	standard = ""
	spec_version = ""
	document_format = "XML"
	#: name of the tax authority, used in messages (the platform's status fields stay generic)
	tax_authority = ""
	#: canonical document types / tax categories this engine can render
	document_types = ()
	tax_categories = ()
	#: seed values for the Compliance Profile record created at install
	profile_defaults = {}

	def __init__(self, profile=None):
		self.profile = dict(self.profile_defaults)
		self.profile.update({k: v for k, v in (profile or {}).items() if v not in (None, "")})

	# ------------------------------------------------------------ descriptive
	def get_country_profile(self):
		"""Static description of the engine plus its effective settings."""
		return {
			"engine_code": self.code,
			"label": self.label,
			"country": self.country,
			"country_code": self.country_code,
			"standard": self.standard,
			"spec_version": self.spec_version,
			"tax_authority": self.tax_authority,
			"document_format": self.document_format,
			"document_types": list(self.get_supported_document_types()),
			"tax_categories": list(self.get_supported_tax_categories()),
			"settings": dict(self.profile),
		}

	def get_supported_document_types(self):
		return tuple(self.document_types)

	def get_supported_tax_categories(self):
		return tuple(self.tax_categories)

	def tax_code(self, category):
		"""Country tax category code for a canonical category, ``None`` when not supported."""
		return None

	# ------------------------------------------------------------ pipeline
	def normalize_invoice(self, invoice):
		"""Country-neutral normalisation followed by :meth:`enrich`."""
		from thinknxg_einvoice_hub.canonical.normalizer import normalize

		return self.enrich(normalize(invoice))

	def enrich(self, invoice):
		"""Derive country-specific identifiers (e.g. participant IDs). Returns the invoice."""
		return invoice

	@abstractmethod
	def validate(self, invoice):
		"""Return a list of issue dicts (severity, rule_id, field_path, message)."""

	def validate_invoice(self, invoice):
		return self.validate(invoice)

	@abstractmethod
	def generate_document(self, invoice):
		"""Return ``{"content": str, "format": "XML"|"JSON", "media_type": str}``."""

	def delivery_expected(self, invoice):
		"""False when the receiver is outside Peppol and only tax reporting will follow submission."""
		return True

	def validate_document(self, document, invoice=None):
		"""Optional check of the generated document (e.g. official Schematron). Default: nothing to add."""
		return []

	@abstractmethod
	def parse_document(self, content):
		"""Parse a received compliance document into a canonical invoice."""

	def participant_id(self, party):
		"""Network address of a party, e.g. ``0235:1000000000``; ``None`` when unknown."""
		return None

	# ------------------------------------------------------------ provider responses
	def map_transaction_status(self, raw_status):
		"""Map a provider/authority status word to a generic lifecycle value (or ``None``)."""
		if raw_status in (None, ""):
			return None
		return GENERIC_STATUS.get(str(raw_status).strip().lower().replace(" ", "_"))

	def parse_provider_response(self, response):
		"""Country-specific post-processing of a normalised provider response dict.

		ASP adapters already normalise transport-level responses; engines may add
		country meaning (e.g. authority acknowledgement codes). Default: unchanged.
		"""
		return response
