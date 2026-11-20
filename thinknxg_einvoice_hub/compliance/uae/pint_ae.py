"""UAE compliance engine: Peppol PINT AE (UBL 2.1).

Scope of this engine
* derives the participant identifier (scheme 0235 + TIN = first 10 digits of the TRN)
* runs the hub's baseline pre-submission checks (see ``validator.py``)
* renders / parses the PINT AE UBL Invoice and CreditNote

* optionally runs the official PINT AE Schematron on the generated document
  (``schematron.py``; the official resources are installed by the operator)

The generator targets Peppol PINT AE 1.0.5 (billing and self-billing). Digital
signing and Tax Data Document reporting to the Federal Tax Authority are performed
by the Accredited Service Provider, not by this app.
"""

import re
import uuid

from thinknxg_einvoice_hub.compliance.base import BaseComplianceEngine
from thinknxg_einvoice_hub.compliance.uae import codes, schematron, tax_rules, ubl_generator, validator

TRN_RE = re.compile(r"^\d{15}$")

CUSTOMIZATION_ID = "urn:peppol:pint:billing-1@ae-1"
PROFILE_ID = "urn:peppol:bis:billing"
SELFBILLING_CUSTOMIZATION_ID = "urn:peppol:pint:selfbilling-1@ae-1"
SELFBILLING_PROFILE_ID = "urn:peppol:bis:selfbilling"
ENDPOINT_SCHEME = "0235"
#: Namespace for the deterministic BTAE-07 UUID when the ERP does not send one (hub-defined, not official)
UUID_NAMESPACE = uuid.UUID("5d0c1f3e-7a2b-4f6e-9c1d-ae0105000000")


class PintAEEngine(BaseComplianceEngine):
	code = "uae_pint_ae"
	label = "UAE - Peppol PINT AE"
	country = "United Arab Emirates"
	country_code = "AE"
	tax_authority = "Federal Tax Authority"
	document_types = ("INVOICE", "CREDIT_NOTE", "SELF_BILLING_INVOICE", "SELF_BILLING_CREDIT_NOTE")
	tax_categories = tuple(tax_rules.CATEGORY_CODES)
	standard = "PINT AE / UBL 2.1"
	spec_version = codes.SPEC_VERSION
	uses_document_uuid = True
	document_format = "XML"
	profile_defaults = {
		"customization_id": CUSTOMIZATION_ID,
		"profile_id": PROFILE_ID,
		"selfbilling_customization_id": SELFBILLING_CUSTOMIZATION_ID,
		"selfbilling_profile_id": SELFBILLING_PROFILE_ID,
		"endpoint_scheme": ENDPOINT_SCHEME,
		"default_currency": "AED",
		"official_validation": "if_configured",
	}

	def enrich(self, invoice):
		doc = invoice.setdefault("document", {})
		doc["tax_currency"] = doc.get("tax_currency") or self.profile["default_currency"]
		flags = doc["transaction_type_flags"] = doc.get("transaction_type_flags") or "00000000"
		for role in ("supplier", "customer"):
			party = invoice.setdefault(role, {})
			country = (party.get("address") or {}).get("country")
			if not party.get("tin") and country == "AE" and TRN_RE.match(party.get("tax_id") or ""):
				party["tin"] = party["tax_id"][:10]
			if party.get("tin") and not party.get("endpoint_scheme"):
				party["endpoint_scheme"] = self.profile["endpoint_scheme"]
		customer = invoice["customer"]
		if not customer.get("tin"):
			# predefined buyer electronic addresses of PINT AE 1.0.5 for buyers outside the network
			country = (customer.get("address") or {}).get("country")
			if codes.flag(flags, codes.FLAG_DEEMED_SUPPLY):
				customer["tin"] = codes.DEEMED_SUPPLY_ENDPOINT
			elif codes.flag(flags, codes.FLAG_EXPORT) and country and country != "AE":
				customer["tin"] = codes.EXPORT_ENDPOINT
			if customer.get("tin"):
				customer["endpoint_scheme"] = self.profile["endpoint_scheme"]
		if not doc.get("uuid"):
			doc["uuid"] = self.document_uuid(invoice)
		return invoice

	def document_uuid(self, invoice):
		"""Stable BTAE-07 UUID: the same document always gets the same identifier, so retries and
		re-generation do not mint a new one. ERP-supplied UUIDs always win."""
		doc = invoice.get("document") or {}
		key = "|".join(str(x or "") for x in ((invoice.get("supplier") or {}).get("tax_id"), doc.get("document_type"),
			doc.get("invoice_number"), doc.get("invoice_date")))
		return str(uuid.uuid5(UUID_NAMESPACE, key))

	def tax_code(self, category):
		return tax_rules.category_code(category)

	def validate(self, invoice):
		return validator.validate(invoice)

	def generate_document(self, invoice):
		return {
			"content": ubl_generator.build(invoice, self.profile),
			"format": "XML",
			"media_type": "application/xml",
			"document_uuid": (invoice.get("document") or {}).get("uuid"),
		}

	def validate_document(self, document, invoice=None):
		"""Run the official PINT AE Schematron on a generated document when configured."""
		mode = self.profile.get("official_validation") or "if_configured"
		if mode == "off":
			return []
		doc_type = ((invoice or {}).get("document") or {}).get("document_type") or ""
		issues = schematron.validate(document["content"], self.profile, credit=doc_type in ubl_generator.CREDIT_TYPES,
			selfbilling=doc_type in ubl_generator.SELF_BILLING)
		if mode == "required":
			for i in issues:
				if i["rule_id"] == schematron.NOT_RUN:
					i["severity"] = "Error"
		return issues

	def get_country_profile(self):
		info = super().get_country_profile()
		info.update({
			"credit_reason_codes": dict(codes.CREDIT_REASONS),
			"exemption_codes": dict(codes.EXEMPTION_REASONS),
			"rcm_goods_types": dict(codes.RCM_GOODS_TYPES),
			"item_types": dict(codes.ITEM_TYPES),
			"billing_frequencies": list(codes.BILLING_FREQUENCIES),
			"legal_registration_types": dict(codes.LEGAL_REGISTRATION_TYPES),
			"predefined_endpoints": {"deemed_supply": codes.DEEMED_SUPPLY_ENDPOINT,
				"not_subject": codes.NOT_SUBJECT_ENDPOINT, "export": codes.EXPORT_ENDPOINT},
			"official_schematron": schematron.describe(self.profile.get("schematron_dir")),
		})
		return info

	def parse_document(self, content):
		return ubl_generator.parse(content)

	def participant_id(self, party):
		party = party or {}
		if not party.get("tin"):
			return None
		return f"{party.get('endpoint_scheme') or self.profile['endpoint_scheme']}:{party['tin']}"
