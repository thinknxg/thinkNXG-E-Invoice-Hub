"""Hub-side validation for Oman PINT OM (rule IDs ``EIH-OM-*``).

Each check corresponds to a rule of the official PINT OM ruleset 1.0.1, named in
the message, and runs on the canonical invoice *before* the XML is generated, so
the ERP gets a field path it can fix. Checks that need the official code lists
(HS and ISIC membership) or the full XPath rule set run in
:mod:`thinknxg_einvoice_hub.compliance.oman.schematron` when the official
resources are installed. The accredited service provider's validation remains
authoritative.

Rule-ID ranges: 001-009 header, 010-029 parties, 030-039 references,
040-049 tax categories, 050-069 lines, 070-079 totals.
"""

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from thinknxg_einvoice_hub.compliance.oman import constants as C
from thinknxg_einvoice_hub.compliance.oman import identifiers, transaction_types
from thinknxg_einvoice_hub.utils import currency_places, issue, to_decimal, to_iso_date

ZERO = Decimal("0")
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
TIME_RE = re.compile(r"^\d{2}:\d{2}:\d{2}$")
DIGITS_RE = re.compile(r"^\d+$")
FULL_ADDRESS = ("street", "additional_street", "address_line", "city", "postal_code")


def _d(value):
	return to_decimal(value, ZERO)


def _decimals(value):
	d = to_decimal(value)
	if d is None:
		return 0
	exp = d.normalize().as_tuple().exponent
	return -exp if exp < 0 else 0


def muscat_today():
	return datetime.now(timezone(timedelta(hours=C.MUSCAT_UTC_OFFSET_HOURS))).date().isoformat()


class Validator:
	def __init__(self, profile, rules):
		self.profile = profile or {}
		self.rules = rules
		self.vatin_pattern = self.profile.get("vatin_pattern") or identifiers.VATIN_PATTERN

	def validate(self, inv):
		issues = []
		doc = inv.get("document") or {}
		flags = doc.get("transaction_type_flags") or ""
		active = set(transaction_types.names(flags))
		self._header(inv, doc, flags, active, issues)
		self._parties(inv, active, issues)
		self._references(inv, doc, active, issues)
		self._lines(inv, doc, active, issues)
		self._allowances(inv, doc, active, issues)
		self._breakdown(inv, doc, active, issues)
		self._totals(inv, doc, issues)
		return issues

	# ------------------------------------------------------------------ header
	def _header(self, inv, doc, flags, active, issues):
		doc_type = doc.get("document_type")
		if doc_type not in C.TYPE_CODES:
			issues.append(issue("Error", "EIH-OM-001", "document.document_type",
				f"Document type '{doc_type}' is not available in PINT OM ({', '.join(C.TYPE_CODES)})"))
		if (doc.get("invoice_kind") or "TAX") != "TAX":
			issues.append(issue("Error", "EIH-OM-001", "document.invoice_kind", "PINT OM carries tax invoices only"))
		if not doc.get("invoice_number"):
			issues.append(issue("Error", "EIH-OM-002", "document.invoice_number", "Invoice number (IBT-001) is required"))
		date = to_iso_date(doc.get("invoice_date"))
		if not date:
			issues.append(issue("Error", "EIH-OM-003", "document.invoice_date", "Invoice issue date (IBT-002) is required"))
		elif date > muscat_today():
			issues.append(issue("Error", "EIH-OM-003", "document.invoice_date",
				"Invoice issue date must not be in the future, Muscat time (IBR-171-OM)"))
		time = doc.get("issue_time")
		if not time:
			issues.append(issue("Error", "EIH-OM-004", "document.issue_time",
				"Invoice issue time (IBT-168, hh:mm:ss) is required (ALIGNED-IBRP-016-OM)"))
		elif not TIME_RE.match(str(time)):
			issues.append(issue("Error", "EIH-OM-004", "document.issue_time", f"Issue time '{time}' must be hh:mm:ss"))
		currency = doc.get("currency") or ""
		if not CURRENCY_RE.match(currency):
			issues.append(issue("Error", "EIH-OM-005", "document.currency", "Invoice currency (IBT-005) must be an ISO 4217 code"))
		elif currency != C.TAX_CURRENCY:
			rate = to_decimal(doc.get("exchange_rate"))
			if rate is None or rate <= 0 or rate == 1:
				issues.append(issue("Error", "EIH-OM-006", "document.exchange_rate",
					f"A {currency} invoice needs the exchange rate to OMR (IBR-004-OM)"))
			elif _decimals(rate) > 7:
				issues.append(issue("Error", "EIH-OM-006", "document.exchange_rate",
					"The exchange rate may have at most 7 decimals (IBR-005-OM)"))
		if doc.get("uuid") and not identifiers.is_uuid_v5(doc["uuid"]):
			issues.append(issue("Error", "EIH-OM-007", "document.uuid",
				"Invoice UUID (BTOM-002) must be a version 5 UUID; leave it empty and the hub computes it (IBR-002-OM)"))

		# BTOM-001
		requested = transaction_types.requested(inv)
		unknown = [n for n in requested or [] if n not in C.TRANSACTION_TYPES]
		if unknown:
			issues.append(issue("Error", "EIH-OM-008", "extensions.om.transaction_types",
				f"Unknown Oman transaction type(s): {', '.join(unknown)}"))
		elif not transaction_types.FLAGS_RE.match(flags):
			issues.append(issue("Error", "EIH-OM-008", "document.transaction_type_flags",
				"Transaction type (BTOM-001) must be 20 characters of 0 and 1 (IBR-001-OM)"))
		else:
			if ("FULL_TAX_INVOICE" in active) == ("SIMPLIFIED_TAX_INVOICE" in active):
				issues.append(issue("Error", "EIH-OM-008", "document.transaction_type_flags",
					"Exactly one of Full Tax Invoice (position 1) or Simplified Tax Invoice (position 2) must be set "
					"(IBR-043-OM, CL-03-OM-1)"))
			for a, b in transaction_types.conflicts(flags):
				if {a, b} != {"FULL_TAX_INVOICE", "SIMPLIFIED_TAX_INVOICE"}:
					issues.append(issue("Error", "EIH-OM-009", "document.transaction_type_flags",
						f"Transaction types {a} and {b} cannot be combined (IBR-138..152-OM, IBR-176-OM)"))
			if doc_type in C.SELF_BILLING and not active & {"SELF_BILLED", "PROFIT_MARGIN_SELF_INVOICE"}:
				issues.append(issue("Error", "EIH-OM-009", "document.transaction_type_flags",
					"A self-billing document needs the Self-billed or Profit Margin Self-Invoice transaction type (IBR-177-OM)"))
		if active & {"SUMMARY", "CONTINUOUS_SUPPLY"}:
			start, end = doc.get("period_start"), doc.get("period_end")
			if not (start and end):
				issues.append(issue("Error", "EIH-OM-033", "document.period_start",
					"Summary and continuous-supply invoices need an invoicing period start and end (IBR-037-OM)"))
			elif "SUMMARY" in active and str(start)[:7] != str(end)[:7]:
				issues.append(issue("Error", "EIH-OM-033", "document.period_end",
					"A summary invoice period must fall in one calendar month (IBR-036-OM)"))

	# ------------------------------------------------------------------ parties
	def _vatin(self, party, role, required, rule, issues):
		vatin = party.get("tax_id")
		if not vatin:
			if required:
				issues.append(issue("Error", "EIH-OM-015", f"{role}.tax_id", f"{role.capitalize()} Oman VATIN is required ({rule})"))
			return
		country = (party.get("address") or {}).get("country")
		if (country in (None, "", "OM") or str(vatin).startswith("OM")) and not identifiers.is_vatin(vatin, self.vatin_pattern):
			issues.append(issue("Error", "EIH-OM-016", f"{role}.tax_id",
				f"{role.capitalize()} VATIN '{vatin}' must be 'OM' followed by 10 digits"))

	def _address(self, party, role, fields, rule, issues):
		addr = party.get("address") or {}
		for field in fields:
			if not addr.get(field):
				issues.append(issue("Error", "EIH-OM-012", f"{role}.address.{field}",
					f"{role.capitalize()} address {field.replace('_', ' ')} is required ({rule})"))

	def _country(self, party, role, issues):
		addr = party.get("address") or {}
		country = addr.get("country")
		if not country or len(country) != 2:
			issues.append(issue("Error", "EIH-OM-011", f"{role}.address.country",
				f"{role.capitalize()} country must be an ISO 3166-1 alpha-2 code"))
		sub = addr.get("subdivision")
		if sub and sub not in C.SUBDIVISIONS:
			issues.append(issue("Error", "EIH-OM-014", f"{role}.address.subdivision",
				f"'{sub}' is not an Oman subdivision code ({', '.join(C.SUBDIVISIONS)}; CL-13-OM)"))

	def _identifier(self, party, role, issues):
		scheme = party.get("identifier_scheme")
		if party.get("identifier") and scheme not in C.IDENTIFIER_SCHEMES:
			issues.append(issue("Error", "EIH-OM-019", f"{role}.identifier_scheme",
				f"A {role} identifier needs a CL-06-OM scheme ({', '.join(C.IDENTIFIER_SCHEMES)}); got '{scheme or ''}'"))

	def _parties(self, inv, active, issues):
		sup = inv.get("supplier") or {}
		cus = inv.get("customer") or {}
		for role, party in (("supplier", sup), ("customer", cus)):
			if not party.get("legal_name"):
				issues.append(issue("Error", "EIH-OM-010", f"{role}.legal_name", f"{role.capitalize()} legal name is required"))
			self._identifier(party, role, issues)
			self._country(party, role, issues)

		# seller
		seller_optional = active & {"IMPORT_OF_GOODS", "IMPORT_OF_SERVICES_RCM", "PROFIT_MARGIN_SELF_INVOICE"}
		self._vatin(sup, "supplier", not seller_optional, "IBR-006-OM", issues)
		if (seller_optional | (active & {"SPECIAL_ZONE"})) and not sup.get("identifier"):
			issues.append(issue("Error", "EIH-OM-019", "supplier.identifier",
				"Seller identifier with scheme is required for import, profit-margin self-invoice and special-zone "
				"transaction types (IBR-007-OM)"))
		self._address(sup, "supplier", FULL_ADDRESS, "IBR-010-OM", issues)
		if not (sup.get("contact") or {}).get("phone"):
			issues.append(issue("Error", "EIH-OM-017", "supplier.contact.phone",
				"Seller contact telephone (IBT-042) is required (IBR-011-OM)"))
		if sup.get("uuid") and not identifiers.is_uuid_v5(sup["uuid"]):
			issues.append(issue("Error", "EIH-OM-018", "supplier.uuid", "Seller UUID (BTOM-004) must be a version 5 UUID"))
		if not sup.get("tin"):
			issues.append(issue("Error", "EIH-OM-020", "supplier.tin",
				"Seller electronic address (IBT-034, scheme 0248) is missing; set the VATIN or the network address"))
		if "PROFIT_MARGIN_SELF_INVOICE" in active and (sup.get("address") or {}).get("country") != "OM":
			issues.append(issue("Error", "EIH-OM-022", "supplier.address.country",
				"Seller country must be OM for a profit-margin self-invoice (IBR-087-OM)"))
		if "IMPORT_OF_SERVICES_RCM" in active and (sup.get("address") or {}).get("country") == "OM":
			issues.append(issue("Error", "EIH-OM-022", "supplier.address.country",
				"Seller country must not be OM for import of services (IBR-160-OM)"))

		# buyer
		b2c = cus.get("tin") == C.B2C_PARTICIPANT
		vatin_required = active & {"SELF_BILLED", "IMPORT_OF_SERVICES_RCM", "PROFIT_MARGIN_SELF_INVOICE", "IMPORT_OF_GOODS"}
		self._vatin(cus, "customer", bool(vatin_required), "IBR-017-OM", issues)
		id_required = active & {"FULL_TAX_INVOICE", "THIRD_PARTY", "SUMMARY", "CONTINUOUS_SUPPLY", "EXPORT",
			"PROFIT_MARGIN", "E_COMMERCE"}
		if id_required and not (cus.get("tax_id") or cus.get("identifier")):
			issues.append(issue("Error", "EIH-OM-021", "customer.tax_id",
				"Buyer VATIN or buyer identifier with scheme is required for this transaction type (IBR-016-OM)"))
		addr_required = active & {"FULL_TAX_INVOICE", "THIRD_PARTY", "SELF_BILLED", "EXPORT", "IMPORT_OF_SERVICES_RCM",
			"PROFIT_MARGIN", "PROFIT_MARGIN_SELF_INVOICE", "IMPORT_OF_GOODS", "SPECIAL_ZONE", "SUMMARY"}
		if addr_required:
			self._address(cus, "customer", FULL_ADDRESS, "IBR-019-OM", issues)
		if vatin_required and (cus.get("address") or {}).get("country") != "OM":
			issues.append(issue("Error", "EIH-OM-022", "customer.address.country",
				"Buyer country must be OM for self-billed, import and profit-margin self-invoice types (IBR-020-OM)"))
		if "IMPORT_OF_GOODS" in active and cus.get("identifier_scheme") != "ICID":
			issues.append(issue("Error", "EIH-OM-019", "customer.identifier_scheme",
				"Import of goods needs the buyer's Importer Customs ID (scheme ICID) (IBR-153-OM)"))
		if b2c and not sup.get("uuid"):
			issues.append(issue("Error", "EIH-OM-018", "supplier.uuid",
				f"A B2C invoice (buyer {C.ENDPOINT_SCHEME}:{C.B2C_PARTICIPANT}) needs the Seller UUID (IBR-173-OM)"))
		if not cus.get("tin"):
			issues.append(issue("Warning", "EIH-OM-023", "customer.tin",
				"Buyer electronic address is empty; the accredited provider must route the invoice another way or "
				"use a substitute participant ID (OM SRA 10.3.1)"))

	# ------------------------------------------------------------------ references
	def _references(self, inv, doc, active, issues):
		refs = inv.get("references") or {}
		type_code = C.TYPE_CODES.get(doc.get("document_type"))
		if type_code in C.ADJUSTMENT_CODES:
			code = refs.get("credit_reason_code")
			if not code:
				issues.append(issue("Error", "EIH-OM-030", "references.credit_reason_code",
					f"Credit note reason code (BTOM-032) is required: {', '.join(C.CREDIT_REASON_CODES)} (IBR-023-OM)"))
			elif code not in C.CREDIT_REASON_CODES:
				issues.append(issue("Error", "EIH-OM-030", "references.credit_reason_code",
					f"'{code}' is not in CL-02-OM ({', '.join(C.CREDIT_REASON_CODES)})"))
		if type_code in C.ADJUSTMENT_CODES or "PROFIT_MARGIN" in active:
			for field, term in (("original_invoice_number", "IBT-025"), ("original_invoice_uuid", "BTOM-031")):
				if not refs.get(field):
					issues.append(issue("Error", "EIH-OM-031", f"references.{field}",
						f"Preceding invoice reference ({term}) is required (IBR-032-OM, IBR-175-OM)"))
			if type_code in C.ADJUSTMENT_CODES and not refs.get("original_invoice_date"):
				issues.append(issue("Error", "EIH-OM-031", "references.original_invoice_date",
					"Preceding invoice issue date (IBT-026) is required (IBR-032-OM)"))
		if refs.get("original_invoice_uuid") and not identifiers.is_uuid_v5(refs["original_invoice_uuid"]):
			issues.append(issue("Error", "EIH-OM-032", "references.original_invoice_uuid",
				"Preceding invoice UUID must be the original invoice's version 5 UUID"))
		if _d((inv.get("totals") or {}).get("prepaid_amount")) and not (refs.get("prepayment_number") and refs.get("prepayment_uuid")):
			issues.append(issue("Error", "EIH-OM-034", "references.prepayment_uuid",
				"A prepaid amount needs the prepayment invoice number and UUID (IBR-058-OM)"))
		delivery = inv.get("delivery") or {}
		dcountry = (delivery.get("address") or {}).get("country")
		if "EXPORT" in active and not dcountry:
			issues.append(issue("Error", "EIH-OM-035", "delivery.address.country",
				"Export invoices need the deliver-to country (IBR-014-OM)"))
		if "IMPORT_OF_GOODS" in active:
			for field, term in (("import_date", "BTOM-030"), ("customs_declaration", "BTOM-021"), ("incoterms", "BTOM-022")):
				if not delivery.get(field):
					issues.append(issue("Error", "EIH-OM-036", f"delivery.{field}", f"Import of goods needs {term} (IBR-085-OM)"))
		if delivery.get("incoterms") and delivery["incoterms"] not in C.INCOTERMS:
			issues.append(issue("Error", "EIH-OM-036", "delivery.incoterms", f"'{delivery['incoterms']}' is not in CL-09-OM"))
		if "E_COMMERCE" in active:
			addr = delivery.get("address") or {}
			for field in FULL_ADDRESS + ("country",):
				if not addr.get(field):
					issues.append(issue("Error", "EIH-OM-035", f"delivery.address.{field}",
						"E-commerce invoices need the full deliver-to address (IBR-040-OM)"))
		pm = ((inv.get("extensions") or {}).get("om") or {}).get("pm_total")
		if active & {"PROFIT_MARGIN", "PROFIT_MARGIN_SELF_INVOICE"} and pm in (None, ""):
			issues.append(issue("Error", "EIH-OM-037", "extensions.om.pm_total",
				"Profit-margin invoices need the total amount due (BTOM-020) (IBR-082-OM)"))

	# ------------------------------------------------------------------ lines
	def _lines(self, inv, doc, active, issues):
		lines = inv.get("lines") or []
		if not lines:
			issues.append(issue("Error", "EIH-OM-050", "lines", "At least one invoice line is required"))
		simplified = "SIMPLIFIED_TAX_INVOICE" in active
		industry_optional = simplified or bool(active & {"IMPORT_OF_GOODS", "IMPORT_OF_SERVICES_RCM", "PROFIT_MARGIN_SELF_INVOICE"})
		date = doc.get("invoice_date")
		dp = currency_places(doc.get("currency"))
		for i, line in enumerate(lines):
			p = f"lines[{i}]"
			if not (line.get("item_name") or line.get("description")):
				issues.append(issue("Error", "EIH-OM-051", f"{p}.item_name", "Item name (IBT-153) is required"))
			item_type = line.get("item_type")
			if item_type and item_type not in C.ITEM_TYPES:
				issues.append(issue("Error", "EIH-OM-052", f"{p}.item_type", "Item type must be G (goods) or S (services) (CL-07-OM)"))
			elif not item_type and not simplified:
				issues.append(issue("Error", "EIH-OM-052", f"{p}.item_type",
					"Goods or services identification (BTOM-019, G or S) is required (IBR-078-OM)"))
			hs = line.get("commodity_code")
			if item_type == "G" and not hs:
				issues.append(issue("Error", "EIH-OM-053", f"{p}.commodity_code",
					"Goods need a 12-digit Oman HS code (IBR-079-OM, IBR-174-OM)"))
			if hs and not (len(str(hs)) == C.HS_LENGTH and DIGITS_RE.match(str(hs))):
				issues.append(issue("Error", "EIH-OM-053", f"{p}.commodity_code",
					f"HS code '{hs}' must be exactly 12 digits (IBR-080-OM)"))
			isic = line.get("industry_code")
			if not isic and not industry_optional:
				issues.append(issue("Error", "EIH-OM-054", f"{p}.industry_code",
					"Industrial classification code (BTOM-033, 6-digit ISIC) is required (IBR-081-OM)"))
			if isic and not (len(str(isic)) == C.ISIC_LENGTH and DIGITS_RE.match(str(isic))):
				issues.append(issue("Error", "EIH-OM-054", f"{p}.industry_code", f"ISIC code '{isic}' must be 6 digits (CL-08-OM-ISIC)"))
			service_type = line.get("service_type")
			if service_type and service_type not in C.SERVICE_TYPES:
				issues.append(issue("Error", "EIH-OM-055", f"{p}.service_type", f"'{service_type}' is not in CL-12-OM"))
			if "IMPORT_OF_GOODS" in active and not line.get("origin_country"):
				issues.append(issue("Error", "EIH-OM-056", f"{p}.origin_country",
					"Import of goods needs the item country of origin (IBR-084-OM)"))
			if active & {"PROFIT_MARGIN", "PROFIT_MARGIN_SELF_INVOICE"} and line.get("profit_margin_code") not in C.PROFIT_MARGIN_CODES:
				issues.append(issue("Error", "EIH-OM-057", f"{p}.profit_margin_code",
					f"Profit-margin lines need a reason code from CL-11-OM ({', '.join(C.PROFIT_MARGIN_CODES)})"))
			if "PROFIT_MARGIN_SELF_INVOICE" in active and line.get("tax_category") != "OUT_OF_SCOPE":
				issues.append(issue("Error", "EIH-OM-058", f"{p}.tax_category",
					"Profit-margin self-invoice lines must be OUT_OF_SCOPE (O) (IBR-086-OM)"))
			for field in ("quantity", "unit_price", "net_amount"):
				if _d(line.get(field)) < 0:
					issues.append(issue("Error", "EIH-OM-059", f"{p}.{field}",
						"Amounts and quantities must be zero or positive; credit notes carry positive values (IBR-137-OM)"))
			issues.extend(self.rules.check(line.get("tax_category"), line.get("tax_rate"), line.get("tax_amount"),
				line.get("exemption_reason_code"), f"{p}.tax_category", date, simplified))
			if line.get("tax_category") == "STANDARD":
				expected = _d(line.get("net_amount")) * _d(line.get("tax_rate")) / 100
				if abs(_d(line.get("tax_amount")) - expected) > Decimal("0.001") + Decimal(1).scaleb(-dp) / 2:
					issues.append(issue("Error", "EIH-OM-060", f"{p}.tax_amount",
						f"Line VAT {line.get('tax_amount')} differs from net amount x rate ({expected:.3f}) (IBR-168-OM)"))
			if "SUMMARY" in active and line.get("period_start") and str(line["period_start"])[:7] != str(line.get("period_end"))[:7]:
				issues.append(issue("Error", "EIH-OM-061", f"{p}.period_end",
					"Summary-invoice line periods must fall in one calendar month (IBR-057-OM)"))
		if "EXPORT" in active and any(l.get("exemption_reason_code") == "VATZR-OM-09" for l in lines) \
				and not any(l.get("item_type") == "S" for l in lines):
			issues.append(issue("Error", "EIH-OM-055", "lines", "Export of services needs a service-type line (IBR-155-OM)"))

	def _allowances(self, inv, doc, active, issues):
		for i, ac in enumerate(inv.get("allowances_charges") or []):
			issues.extend(self.rules.check(ac.get("tax_category"), ac.get("tax_rate"), 0,
				ac.get("exemption_reason_code"), f"allowances_charges[{i}].tax_category", doc.get("invoice_date"),
				"SIMPLIFIED_TAX_INVOICE" in active))

	# ------------------------------------------------------------------ breakdown / totals
	def _breakdown(self, inv, doc, active, issues):
		rows = inv.get("tax_breakdown") or []
		seen = {}
		for i, row in enumerate(rows):
			cat = row.get("tax_category")
			seen[cat] = seen.get(cat, 0) + 1
			if cat in ("EXEMPT", "ZERO_RATED") and not row.get("exemption_reason_code"):
				issues.append(issue("Error", "EIH-OM-045", f"tax_breakdown[{i}].exemption_reason_code",
					"Exempt and zero-rated VAT breakdowns need a reason code (IBR-069-OM)"))
		if "SIMPLIFIED_TAX_INVOICE" not in active:
			for cat in ("EXEMPT", "ZERO_RATED", "OUT_OF_SCOPE"):
				if seen.get(cat, 0) > 1:
					issues.append(issue("Error", "EIH-OM-048", "tax_breakdown",
						f"Only one VAT breakdown for category {self.rules.code(cat)} is allowed (ALIGNED-IBRP-E/O/Z-01-OM)"))
		dp = currency_places(doc.get("currency"))
		lines = inv.get("lines") or []
		for i, row in enumerate(rows):
			cat, rate = row.get("tax_category"), _d(row.get("tax_rate"))
			if cat != "STANDARD":
				continue
			line_vat = sum((_d(l.get("tax_amount")) for l in lines
				if l.get("tax_category") == cat and _d(l.get("tax_rate")) == rate), ZERO)
			ac_vat = ZERO
			for ac in inv.get("allowances_charges") or []:
				if ac.get("tax_category") == cat and _d(ac.get("tax_rate")) == rate:
					v = _d(ac.get("amount")) * rate / 100
					ac_vat += v if ac.get("is_charge") else -v
			tolerance = Decimal("0.001") * max(len(lines), 1) + Decimal(1).scaleb(-dp)
			if abs(_d(row.get("tax_amount")) - (line_vat + ac_vat)) > tolerance:
				issues.append(issue("Error", "EIH-OM-070", f"tax_breakdown[{i}].tax_amount",
					f"Category S VAT {row.get('tax_amount')} differs from line VAT plus charges minus allowances "
					f"({line_vat + ac_vat:.3f}) (ALIGNED-IBRP-S-09-OM)"))

	def _totals(self, inv, doc, issues):
		totals = inv.get("totals") or {}
		dp = currency_places(doc.get("currency"))
		tol = Decimal(1).scaleb(-dp)
		for key in ("subtotal", "tax_exclusive", "tax_total", "grand_total", "payable_amount", "allowance_total",
				"charge_total", "prepaid_amount"):
			if _d(totals.get(key)) < 0:
				issues.append(issue("Error", "EIH-OM-071", f"totals.{key}", "Totals must not be negative (IBR-137-OM)"))
			if _decimals(totals.get(key)) > 3:
				issues.append(issue("Error", "EIH-OM-072", f"totals.{key}", "Amounts may have at most 3 decimals (IBR-DEC-03-OM)"))
		vat = sum((_d(r.get("tax_amount")) for r in inv.get("tax_breakdown") or []), ZERO)
		if abs(vat - _d(totals.get("tax_total"))) > tol:
			issues.append(issue("Error", "EIH-OM-073", "totals.tax_total",
				f"Total VAT {totals.get('tax_total')} differs from the VAT breakdown sum {vat}"))
		expected = _d(totals.get("tax_exclusive")) + _d(totals.get("tax_total"))
		if abs(expected - _d(totals.get("grand_total"))) > tol:
			issues.append(issue("Error", "EIH-OM-074", "totals.grand_total",
				f"Total with VAT {totals.get('grand_total')} differs from total without VAT plus VAT ({expected})"))
