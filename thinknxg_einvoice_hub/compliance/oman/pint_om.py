"""Oman compliance engine: Fawtara on Peppol PINT OM 1.0.1 (UBL 2.1).

What the hub does for Oman (the seller's side, corner 1)
* derives Oman terms the ERP may not carry: 0248 participant address from the
  VATIN, the 20-position transaction type, substitute participant IDs for
  B2C / export receivers, the Seller UUID and QR payload (B2C and profit margin)
* validates the canonical invoice against the PINT OM rules (``validator.py``)
* renders the PINT OM UBL Invoice / CreditNote with the Invoice UUID computed by
  the published method, and can run the official Schematron on it
* parses inbound PINT OM documents, and maps provider MLS codes to the hub's
  reporting and delivery statuses

What it does not do: transmit over Peppol, build or send the Tax Data Document,
or talk to the Oman Tax Authority. Those are the accredited service provider's
tasks under the 5-corner model (OM SRA 2.2, 5.3-5.4); the hub tracks their outcome.
"""

import copy

from thinknxg_einvoice_hub.compliance.base import BaseComplianceEngine
from thinknxg_einvoice_hub.compliance.oman import constants as C
from thinknxg_einvoice_hub.compliance.oman import identifiers, qr, schematron, status_mapper, transaction_types
from thinknxg_einvoice_hub.compliance.oman.tax_rules import TaxRules
from thinknxg_einvoice_hub.compliance.oman.ubl_generator import Builder, fmt, parse
from thinknxg_einvoice_hub.compliance.oman.validator import Validator
from thinknxg_einvoice_hub.utils import currency_places


class PintOMEngine(BaseComplianceEngine):
	code = "om_pint_om"
	label = "Oman - Fawtara (Peppol PINT OM)"
	country = "Oman"
	country_code = "OM"
	tax_authority = "Oman Tax Authority"
	standard = "PINT OM / UBL 2.1"
	spec_version = C.SPEC_RELEASE
	document_format = "XML"
	document_types = tuple(C.TYPE_CODES)
	tax_categories = tuple(C.CATEGORY_CODES)
	#: credit notes must reference the original invoice's UUID (BTOM-031); the hub fills it from its records
	uses_document_uuid = True
	profile_defaults = {
		"customization_id": C.CUSTOMIZATION_ID,
		"profile_id": C.PROFILE_ID,
		"selfbilling_customization_id": C.SELFBILLING_CUSTOMIZATION_ID,
		"selfbilling_profile_id": C.SELFBILLING_PROFILE_ID,
		"endpoint_scheme": C.ENDPOINT_SCHEME,
		"default_currency": C.TAX_CURRENCY,
		# engine_settings (JSON on the Compliance Profile); all optional
		"uuid_namespace": C.UUID_NAMESPACE,
		"always_seller_uuid": False,
		"schematron_dir": None,
		"selfbilling_schematron_dir": None,
		"official_validation": "if_configured",  # off | if_configured | required
	}

	def __init__(self, profile=None):
		super().__init__(profile)
		self.rules = TaxRules(self.profile)

	def tax_code(self, category):
		return self.rules.code(category)

	# ------------------------------------------------------------ enrichment
	def enrich(self, invoice):
		inv = invoice
		doc = inv.setdefault("document", {})
		om = inv.setdefault("extensions", {}).setdefault("om", {})
		doc["tax_currency"] = self.profile["default_currency"]
		scheme = self.profile["endpoint_scheme"]
		for role in ("supplier", "customer"):
			party = inv.setdefault(role, {})
			if party.get("tax_id"):
				party["tax_id"] = identifiers.clean_vatin(party["tax_id"])
			# the OTA uses the VATIN itself as the Peppol address (scheme 0248)
			if not party.get("tin") and identifiers.is_vatin(party.get("tax_id"), self.profile.get("vatin_pattern") or identifiers.VATIN_PATTERN):
				party["tin"] = party["tax_id"]
			if party.get("tin") and not party.get("endpoint_scheme"):
				party["endpoint_scheme"] = scheme

		customer = inv["customer"]
		if om.get("b2c"):
			# OM SRA 4.3: fixed buyer values for consumers who are not on Peppol
			customer["tin"], customer["endpoint_scheme"] = C.B2C_PARTICIPANT, scheme
			customer.setdefault("legal_name", C.B2C_BUYER_NAME)
			customer.setdefault("address", {}).setdefault("country", "OM")
			if not doc.get("transaction_type_flags") and not om.get("transaction_types"):
				om["transaction_types"] = ["SIMPLIFIED_TAX_INVOICE"]
		elif om.get("substitute_participant") in C.SUBSTITUTE_PARTICIPANTS and not customer.get("tin"):
			customer["tin"] = C.SUBSTITUTE_PARTICIPANTS[om["substitute_participant"]]
			customer["endpoint_scheme"] = scheme

		flags = transaction_types.derive(inv)
		if flags:
			doc["transaction_type_flags"] = flags
		for line in inv.get("lines") or []:
			if line.get("commodity_code") and not line.get("commodity_list"):
				line["commodity_list"] = "HS"
		self._seller_uuid(inv, flags)
		return inv

	def _qr_inputs(self, inv, flags):
		doc, sup, totals = inv["document"], inv.get("supplier") or {}, inv.get("totals") or {}
		dp = currency_places(doc.get("currency"))
		pm = transaction_types.has(flags, "PROFIT_MARGIN")
		pm_total = (inv.get("extensions") or {}).get("om", {}).get("pm_total")
		return dict(
			number=doc.get("invoice_number"), seller_name=sup.get("legal_name"), vatin=sup.get("tax_id"),
			issue_date=doc.get("invoice_date"), issue_time=doc.get("issue_time"),
			total=fmt(pm_total, 3) if pm else fmt(totals.get("grand_total"), dp),
			vat_total=None if pm else fmt(totals.get("tax_total"), dp), profit_margin=pm,
		)

	def _seller_uuid(self, inv, flags):
		"""Seller UUID (BTOM-004) for B2C and profit-margin invoices, and the QR payload that carries it."""
		sup, doc = inv.get("supplier") or {}, inv["document"]
		om = inv["extensions"]["om"]
		b2c = (inv.get("customer") or {}).get("tin") == C.B2C_PARTICIPANT
		pm = transaction_types.has(flags, "PROFIT_MARGIN")
		if not (b2c or pm or self.profile.get("always_seller_uuid")):
			return
		if not all((doc.get("invoice_number"), sup.get("legal_name"), sup.get("tax_id"), doc.get("invoice_date"),
				doc.get("issue_time"))):
			return  # the validator reports the missing field
		args = self._qr_inputs(inv, flags)
		if not sup.get("uuid"):
			inv_type = C.QR_INVOICE_TYPES["PROFIT_MARGIN" if pm else "STANDARD"]
			sup["uuid"] = identifiers.seller_uuid(inv_type, args["number"], args["seller_name"], args["vatin"],
				args["issue_date"], args["issue_time"], args["total"], args["vat_total"],
				namespace=self.profile.get("uuid_namespace"))
		om["qr_base64"] = qr.encode(qr.fields(seller_uuid=sup["uuid"], **args))

	# ------------------------------------------------------------ validation / generation
	def validate(self, invoice):
		return Validator(self.profile, self.rules).validate(invoice)

	def generate_document(self, invoice):
		content, meta = Builder(self.profile, self.rules).build(invoice)
		return {"content": content, "format": "XML", "media_type": "application/xml", "document_uuid": meta["uuid"],
			"meta": meta}

	def validate_document(self, document, invoice=None):
		"""Run the official PINT OM Schematron on a generated document when configured."""
		mode = self.profile.get("official_validation") or "if_configured"
		if mode == "off":
			return []
		doc_type = ((invoice or {}).get("document") or {}).get("document_type") or ""
		issues = schematron.validate(document["content"], self.profile, credit=doc_type in C.CREDIT_TYPES,
			selfbilling=doc_type in C.SELF_BILLING)
		if mode == "required":
			for i in issues:
				if i["rule_id"] == "EIH-OM-090":
					i["severity"] = "Error"
		return issues

	def delivery_expected(self, invoice):
		"""B2C, export and other substitute-participant receivers get no C2->C3 invoice exchange;
		the provider only sends the TDD to the OTA (OM SRA 5.5 and table 3)."""
		receiver = (invoice.get("customer") or {}).get("tin")
		return bool(receiver) and receiver not in C.SUBSTITUTE_PARTICIPANTS.values()

	def parse_document(self, content):
		return parse(content, self.rules)

	def participant_id(self, party):
		party = party or {}
		if not party.get("tin"):
			return None
		return identifiers.participant_id(party["tin"], party.get("endpoint_scheme") or self.profile["endpoint_scheme"])

	# ------------------------------------------------------------ provider responses
	def parse_provider_response(self, response):
		return status_mapper.apply(response)

	def map_transaction_status(self, raw_status):
		return status_mapper.map_status(raw_status) or super().map_transaction_status(raw_status)

	def qr_payload(self, invoice):
		flags = (invoice.get("document") or {}).get("transaction_type_flags")
		args = self._qr_inputs(invoice, flags)
		return qr.encode(qr.fields(seller_uuid=(invoice.get("supplier") or {}).get("uuid"), **args))

	def get_country_profile(self):
		info = super().get_country_profile()
		info.update({
			"transaction_types": list(C.TRANSACTION_TYPES),
			"credit_reason_codes": copy.deepcopy(C.CREDIT_REASON_CODES),
			"exemption_codes": copy.deepcopy(C.EXEMPTION_CODES),
			"zero_rating_codes": copy.deepcopy(C.ZERO_RATING_CODES),
			"profit_margin_codes": copy.deepcopy(C.PROFIT_MARGIN_CODES),
			"identifier_schemes": copy.deepcopy(C.IDENTIFIER_SCHEMES),
			"subdivisions": copy.deepcopy(C.SUBDIVISIONS),
			"service_types": copy.deepcopy(C.SERVICE_TYPES),
			"substitute_participants": copy.deepcopy(C.SUBSTITUTE_PARTICIPANTS),
			"document_type_ids": copy.deepcopy(C.DOCUMENT_TYPE_IDS),
			"tax_data_document": C.TDD_DOCUMENT_TYPE + " (built and sent by the accredited provider)",
			"official_schematron": schematron.ruleset_version(self.profile["schematron_dir"])
			if self.profile.get("schematron_dir") else None,
		})
		return info
