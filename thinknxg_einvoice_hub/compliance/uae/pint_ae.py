"""UAE compliance engine: Peppol PINT AE (UBL 2.1).

Scope of this engine
* derives the participant identifier (scheme 0235 + TIN = first 10 digits of the TRN)
* runs the hub's baseline pre-submission checks (see ``validator.py``)
* renders / parses the PINT AE UBL Invoice and CreditNote

It is a PINT AE-aligned baseline. Authoritative validation (the official PINT AE
Schematron), digital signing and Tax Data Document reporting to the Federal Tax
Authority are performed by the Accredited Service Provider, not by this app.
"""

import re

from thinknxg_einvoice_hub.compliance.base import BaseComplianceEngine
from thinknxg_einvoice_hub.compliance.uae import tax_rules, ubl_generator, validator

TRN_RE = re.compile(r"^\d{15}$")

CUSTOMIZATION_ID = "urn:peppol:pint:billing-1@ae-1"
PROFILE_ID = "urn:peppol:bis:billing"
SELFBILLING_CUSTOMIZATION_ID = "urn:peppol:pint:selfbilling-1@ae-1"
SELFBILLING_PROFILE_ID = "urn:peppol:bis:selfbilling"
ENDPOINT_SCHEME = "0235"


class PintAEEngine(BaseComplianceEngine):
	code = "uae_pint_ae"
	label = "UAE - Peppol PINT AE"
	country = "United Arab Emirates"
	country_code = "AE"
	tax_authority = "Federal Tax Authority"
	document_types = ("INVOICE", "CREDIT_NOTE", "SELF_BILLING_INVOICE", "SELF_BILLING_CREDIT_NOTE")
	tax_categories = tuple(tax_rules.CATEGORY_CODES)
	standard = "PINT AE / UBL 2.1"
	spec_version = "1.0.3"
	document_format = "XML"
	profile_defaults = {
		"customization_id": CUSTOMIZATION_ID,
		"profile_id": PROFILE_ID,
		"selfbilling_customization_id": SELFBILLING_CUSTOMIZATION_ID,
		"selfbilling_profile_id": SELFBILLING_PROFILE_ID,
		"endpoint_scheme": ENDPOINT_SCHEME,
		"default_currency": "AED",
	}

	def enrich(self, invoice):
		doc = invoice.setdefault("document", {})
		doc["tax_currency"] = doc.get("tax_currency") or self.profile["default_currency"]
		doc["transaction_type_flags"] = doc.get("transaction_type_flags") or "00000000"
		for role in ("supplier", "customer"):
			party = invoice.setdefault(role, {})
			country = (party.get("address") or {}).get("country")
			if not party.get("tin") and country == "AE" and TRN_RE.match(party.get("tax_id") or ""):
				party["tin"] = party["tax_id"][:10]
			if party.get("tin") and not party.get("endpoint_scheme"):
				party["endpoint_scheme"] = self.profile["endpoint_scheme"]
		return invoice

	def tax_code(self, category):
		return tax_rules.category_code(category)

	def validate(self, invoice):
		return validator.validate(invoice)

	def generate_document(self, invoice):
		return {
			"content": ubl_generator.build(invoice, self.profile),
			"format": "XML",
			"media_type": "application/xml",
		}

	def parse_document(self, content):
		return ubl_generator.parse(content)

	def participant_id(self, party):
		party = party or {}
		if not party.get("tin"):
			return None
		return f"{party.get('endpoint_scheme') or self.profile['endpoint_scheme']}:{party['tin']}"
