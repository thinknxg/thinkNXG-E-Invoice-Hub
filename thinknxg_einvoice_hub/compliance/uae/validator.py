"""Pre-submission validation for UAE PINT AE 1.0.5.

These are the hub's own checks (rule IDs ``EIH-AE-*``), run before a document is
generated so that missing or inconsistent ERP data is reported against the
canonical field that needs fixing. Each check names the official PINT AE rule it
anticipates (``ibr-*-ae`` / ``aligned-ibrp-*``).

They do not replace the official PINT AE Schematron: run that with the official
resources configured on the Compliance Profile (see ``schematron.py``); the
Accredited Service Provider applies it again on submission.
"""

import re
from decimal import Decimal

from thinknxg_einvoice_hub.canonical.credit_note_schema import validate_credit_note
from thinknxg_einvoice_hub.compliance.uae import codes, tax_rules
from thinknxg_einvoice_hub.utils import get_path, issue, to_decimal, to_iso_date

ZERO = Decimal("0")
TOL = Decimal("0.01")
TRN_RE = re.compile(r"^1\d{12}03$")          # ibr-132-ae: 15 digits, starts with 1, ends with 03
TIN_RE = re.compile(r"^1\d{9}$")              # ibr-148-ae
BUYER_ENDPOINT_RE = re.compile(r"^[19]\d{9}$")  # ibr-149-ae
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
FLAGS_RE = re.compile(r"^[01]{8}$")
COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
EMIRATES = ("AUH", "DXB", "SHJ", "AJM", "UAQ", "RAK", "FUJ")
CREDIT_TYPES = ("CREDIT_NOTE", "SELF_BILLING_CREDIT_NOTE")


def _d(value):
	return to_decimal(value, ZERO)


def _legal_registration(party, role, label, issues, required):
	"""BTAE-15/16 type, BTAE-11/12 authority, BTAE-18/19 passport country."""
	reg_id = party.get("legal_registration_id")
	reg_type = party.get("legal_registration_type")
	authority = party.get("legal_registration_authority")
	if not reg_id:
		if required:
			issues.append(issue("Error", "EIH-AE-019", f"{role}.legal_registration_id",
				f"{label} legal registration identifier (trade licence, Emirates ID, passport or cabinet decision "
				"number) is required (ibr-150-ae / ibr-149-ae / ibr-136-ae)"))
		return
	if not reg_type:
		issues.append(issue("Error", "EIH-AE-020", f"{role}.legal_registration_type",
			f"{label} legal registration type is required: one of {', '.join(codes.LEGAL_REGISTRATION_TYPES)} "
			"(ibr-181-ae / ibr-180-ae)"))
	elif reg_type not in codes.LEGAL_REGISTRATION_TYPES:
		issues.append(issue("Error", "EIH-AE-020", f"{role}.legal_registration_type",
			f"{label} legal registration type '{reg_type}' is not valid for the UAE; use one of "
			f"{', '.join(codes.LEGAL_REGISTRATION_TYPES)} (ibr-173-ae / ibr-183-ae)"))
	if reg_type == "TL" and not authority:
		issues.append(issue("Error", "EIH-AE-021", f"{role}.legal_registration_authority",
			f"{label} trade licence issuing authority name is required (ibr-172-ae / ibr-101-ae)"))
	if reg_type == "PAS" and not COUNTRY_RE.match(authority or ""):
		issues.append(issue("Error", "EIH-AE-022", f"{role}.legal_registration_authority",
			f"{label} passport issuing country must be an ISO 3166-1 alpha-2 code (ibr-012-ae / ibr-010-ae)"))


def _party(inv, role, doc, issues):
	party = inv.get(role) or {}
	addr = party.get("address") or {}
	label = role.capitalize()
	country = addr.get("country")
	is_ae = country == "AE"
	kind = doc.get("invoice_kind") or "TAX"
	commercial = kind == "COMMERCIAL"
	flags = doc.get("transaction_type_flags") or ""

	if not party.get("legal_name"):
		issues.append(issue("Error", "EIH-AE-010", f"{role}.legal_name", f"{label} legal name is required"))
	if not country or len(country) != 2:
		issues.append(issue("Error", "EIH-AE-011", f"{role}.address.country",
			f"{label} country must be an ISO 3166-1 alpha-2 code"))
	for field in ("street", "city"):
		if not addr.get(field):
			issues.append(issue("Error", "EIH-AE-012", f"{role}.address.{field}",
				f"{label} address {field} is required (ibr-143-ae / ibr-144-ae)"))
	if not addr.get("subdivision"):
		issues.append(issue("Error", "EIH-AE-013", f"{role}.address.subdivision",
			f"{label} address subdivision is required (emirate code for UAE addresses, state or region abroad) "
			"(ibr-143-ae / ibr-144-ae)"))
	elif is_ae and addr["subdivision"].upper() not in EMIRATES:
		issues.append(issue("Error", "EIH-AE-014", f"{role}.address.subdivision",
			f"{label} emirate '{addr['subdivision']}' is not one of {', '.join(EMIRATES)} (ibr-128-ae)"))

	trn = party.get("tax_id")
	if role == "supplier" and not commercial and not trn:
		issues.append(issue("Error", "EIH-AE-015", "supplier.tax_id",
			"Supplier TRN is required on a tax invoice (ibr-134-ae)"))
	if trn and is_ae and not TRN_RE.match(trn):
		issues.append(issue("Error", "EIH-AE-016", f"{role}.tax_id",
			f"{label} TRN must be 15 digits, starting with 1 and ending with 03 (ibr-132-ae)"))

	tin = party.get("tin")
	scheme = party.get("endpoint_scheme") or "0235"
	if not tin:
		level = "Error" if role == "supplier" or is_ae else "Warning"
		issues.append(issue(level, "EIH-AE-017", f"{role}.tin",
			f"{label} electronic address (TIN) is missing; it is needed to route the invoice on the network"))
	elif scheme == "0235":
		pattern = TIN_RE if role == "supplier" else BUYER_ENDPOINT_RE
		if not pattern.match(tin):
			issues.append(issue("Error", "EIH-AE-018", f"{role}.tin",
				f"{label} TIN must be 10 digits starting with 1" + ("" if role == "supplier" else
				" (or a predefined 99000000xx address)") + " (ibr-148-ae / ibr-149-ae)"))

	on_0235 = bool(tin) and scheme == "0235"
	predefined = tin in (codes.NOT_SUBJECT_ENDPOINT, codes.EXPORT_ENDPOINT)
	if role == "supplier":
		required = on_0235
	else:
		required = (on_0235 and not BUYER_ENDPOINT_RE.match(tin)) or commercial
	if role == "customer" and predefined and not party.get("legal_registration_id"):
		pass  # BTAE-16 / BTAE-11 optional for 9900000098 / 9900000099 buyers (PINT AE 1.0.5 change 20)
	elif role == "customer" and predefined:
		# type / authority optional, but a passport still needs its issuing country (ibr-010-ae)
		if party.get("legal_registration_type") == "PAS":
			_legal_registration(party, role, label, issues, False)
	else:
		_legal_registration(party, role, label, issues, required)

	if role == "customer" and on_0235 and not TIN_RE.match(tin) and not codes.flag(flags, codes.FLAG_EXPORT) \
			and not (party.get("identifier") or trn):
		issues.append(issue("Error", "EIH-AE-023", "customer.tax_id",
			"Buyer TRN or buyer identifier is required for a buyer without a UAE TIN address (ibr-135-ae)"))


def _document(inv, issues):
	doc = inv.get("document") or {}
	kind = doc.get("invoice_kind") or "TAX"
	doc_type = doc.get("document_type")
	credit = doc_type in CREDIT_TYPES
	currency = doc.get("currency") or ""
	flags = doc.get("transaction_type_flags") or ""
	payment = inv.get("payment") or {}
	deemed = codes.flag(flags, codes.FLAG_DEEMED_SUPPLY)

	if not doc.get("invoice_number"):
		issues.append(issue("Error", "EIH-AE-001", "document.invoice_number", "Invoice number is required"))
	invoice_date = to_iso_date(doc.get("invoice_date"))
	if not invoice_date:
		issues.append(issue("Error", "EIH-AE-002", "document.invoice_date", "Invoice date must be a valid date"))
	if doc.get("due_date") and not to_iso_date(doc["due_date"]):
		issues.append(issue("Error", "EIH-AE-003", "document.due_date", "Due date must be a valid date"))
	if not CURRENCY_RE.match(currency):
		issues.append(issue("Error", "EIH-AE-004", "document.currency", "Currency must be an ISO 4217 code"))
	if not FLAGS_RE.match(flags):
		issues.append(issue("Error", "EIH-AE-005", "document.transaction_type_flags",
			"Transaction type flags must be 8 binary digits, e.g. 00000000 (ibr-154-ae)"))
	if doc.get("tax_currency") and doc["tax_currency"] != "AED":
		issues.append(issue("Error", "EIH-AE-024", "document.tax_currency",
			"VAT accounting currency must be AED (ibr-140-ae)"))
	if currency and currency != "AED" and _d(doc.get("exchange_rate")) in (ZERO, Decimal("1")):
		issues.append(issue("Error", "EIH-AE-006", "document.exchange_rate",
			"Invoice is not in AED; the exchange rate to AED is required (ibr-153-ae / ibr-159-ae)"))
	payable = _d(get_path(inv, "totals.payable_amount"))
	if not credit and not deemed and payable > 0 and not doc.get("due_date"):
		issues.append(issue("Error", "EIH-AE-007", "document.due_date",
			"Payment due date is required when an amount is payable (ibr-127-ae)"))

	means = payment.get("means_code")
	if means and means not in codes.PAYMENT_MEANS:
		issues.append(issue("Error", "EIH-AE-008", "payment.means_code",
			f"Payment means code '{means}' is not in the UAE list ({', '.join(codes.PAYMENT_MEANS)})"))
	if means == "30" and not payment.get("iban"):
		issues.append(issue("Error", "EIH-AE-009", "payment.iban",
			"Credit transfer (payment means 30) needs the payee account identifier (IBAN) (ibr-192-ae)"))
	if not credit and not deemed and not means:
		issues.append(issue("Warning", "EIH-AE-025", "payment.means_code",
			"No payment means sent; the document states 1 (instrument not defined) (ibr-191-ae)"))

	tax_point = to_iso_date(doc.get("tax_point_date"))
	if tax_point and invoice_date:
		if credit:
			issues.append(issue("Warning", "EIH-AE-026", "document.tax_point_date",
				"VAT point date is not allowed on credit notes and is left out (ibr-124-ae)"))
		elif tax_point > invoice_date:
			issues.append(issue("Error", "EIH-AE-026", "document.tax_point_date",
				"VAT point date must be before the invoice date (ibr-141-ae)"))

	# credit notes: BTAE-03 reason and the preceding invoice (ibr-055-ae, ibr-158-ae, ibr-001-ae)
	if credit:
		reason = get_path(inv, "references.credit_reason_code")
		if not reason:
			level = "Error" if doc_type == "CREDIT_NOTE" else "Warning"
			issues.append(issue(level, "EIH-AE-060", "references.credit_reason_code",
				f"Credit note reason code is required: one of {', '.join(codes.CREDIT_REASONS)} (ibr-158-ae / ibr-055-ae)"))
		elif reason not in codes.CREDIT_REASONS:
			issues.append(issue("Error", "EIH-AE-060", "references.credit_reason_code",
				f"Credit note reason code '{reason}' is not in the UAE list ({', '.join(codes.CREDIT_REASONS)}) (ibr-001-ae)"))
		if reason == codes.VOLUME_DISCOUNT and get_path(inv, "references.original_invoice_number"):
			issues.append(issue("Warning", "EIH-AE-061", "references.original_invoice_number",
				"A volume-discount credit note must not reference a preceding invoice; the reference is left out (ibr-055-ae)"))

	# transaction type flags that need extra data (transactiontype.gc)
	period = doc.get("invoice_period") or {}
	if codes.flag(flags, codes.FLAG_SUMMARY) and not (period.get("start_date") or period.get("end_date")):
		issues.append(issue("Error", "EIH-AE-062", "document.invoice_period",
			"A summary invoice (flag position 4) needs the invoicing period (ibr-138-ae)"))
	freq = period.get("frequency_code")
	if freq and freq not in codes.BILLING_FREQUENCIES:
		issues.append(issue("Error", "EIH-AE-063", "document.invoice_period.frequency_code",
			f"Frequency of billing '{freq}' is not one of {', '.join(codes.BILLING_FREQUENCIES)} (ibr-005-ae)"))
	if freq == "OTH" and not doc.get("notes"):
		issues.append(issue("Error", "EIH-AE-063", "document.notes",
			"Frequency of billing 'OTH' needs the frequency stated in the invoice note (ibr-160-ae)"))
	for position, label, rule in ((codes.FLAG_FREE_TRADE_ZONE, "Free trade zone (position 1) needs the "
			"beneficiary's free-zone identifier", "ibr-007-ae"), (codes.FLAG_AGENT_BILLING, "Disclosed agent "
			"billing (position 6) needs the principal (seller supplier party)", "ibr-137-ae / ibr-176-ae")):
		if codes.flag(flags, position):
			issues.append(issue("Error", "EIH-AE-064", "document.transaction_type_flags",
				f"{label}; the hub's PINT AE generator does not support this data yet ({rule})"))
	daddr = get_path(inv, "delivery.address") or {}
	full_delivery = all(daddr.get(k) for k in ("street", "city", "subdivision"))
	if codes.flag(flags, codes.FLAG_ECOMMERCE) and not full_delivery:
		issues.append(issue("Error", "EIH-AE-065", "delivery.address",
			"E-commerce supplies (position 7) need the deliver-to street, city and subdivision (ibr-142-ae)"))
	if codes.flag(flags, codes.FLAG_EXPORT) and daddr and daddr.get("country") != "AE" and not full_delivery:
		issues.append(issue("Error", "EIH-AE-065", "delivery.address",
			"Exports (position 8) with a foreign deliver-to address need its street, city and subdivision (ibr-152-ae)"))
	if kind == "COMMERCIAL" and (codes.flag(flags, codes.FLAG_SUMMARY) or deemed
			or codes.flag(flags, codes.FLAG_MARGIN_SCHEME)):
		issues.append(issue("Error", "EIH-AE-066", "document.transaction_type_flags",
			"Summary, deemed supply and margin scheme flags are not allowed on out-of-scope documents (ibr-157-ae)"))


def _categories(inv, issues):
	doc = inv.get("document") or {}
	kind = doc.get("invoice_kind") or "TAX"
	flags = doc.get("transaction_type_flags") or ""
	used = [l.get("tax_category") for l in inv.get("lines") or []]
	used += [a.get("tax_category") for a in inv.get("allowances_charges") or []]
	if kind == "COMMERCIAL" and any(c not in ("EXEMPT", "OUT_OF_SCOPE") for c in used):
		issues.append(issue("Error", "EIH-AE-045", "lines",
			"Out-of-scope documents (480 / 81) may only use EXEMPT or OUT_OF_SCOPE categories (ibr-122-ae)"))
	line_cats = [l.get("tax_category") for l in inv.get("lines") or []]
	if kind == "TAX" and line_cats and all(c in ("EXEMPT", "OUT_OF_SCOPE") for c in line_cats):
		issues.append(issue("Error", "EIH-AE-045", "lines",
			"A tax invoice or tax credit note needs at least one line that is not EXEMPT or OUT_OF_SCOPE; "
			"use invoice_kind COMMERCIAL (480 / 81) instead (ibr-151-ae)"))
	if codes.flag(flags, codes.FLAG_MARGIN_SCHEME) and any(c != "MARGIN_SCHEME" for c in used):
		issues.append(issue("Error", "EIH-AE-046", "lines",
			"With the margin scheme flag (position 3) every category must be MARGIN_SCHEME (ibr-116-ae)"))


def _line(inv, i, line, issues):
	p = f"lines[{i}]"
	category = line.get("tax_category")
	qty, price, disc = _d(line.get("quantity")), _d(line.get("unit_price")), _d(line.get("discount_amount"))
	net = _d(line.get("net_amount"))
	base = _d(line.get("price_base_quantity")) or Decimal("1")
	if qty == 0:
		issues.append(issue("Error", "EIH-AE-030", f"{p}.quantity", "Quantity must not be zero"))
	if price < 0:
		issues.append(issue("Error", "EIH-AE-031", f"{p}.unit_price", "Unit price must not be negative"))
	if not line.get("unit_code"):
		issues.append(issue("Error", "EIH-AE-032", f"{p}.unit_code", "Unit of measure code is required"))
	if not line.get("item_name") and not line.get("description"):
		issues.append(issue("Error", "EIH-AE-033", f"{p}.item_name", "Item name is required (ibr-125-ae)"))
	expected = qty * price / base - disc
	if abs(expected - net) > TOL:
		issues.append(issue("Error", "EIH-AE-034", f"{p}.net_amount",
			f"Line net amount {net} does not equal quantity x unit price / base quantity - discount "
			f"({expected.quantize(TOL)}) (ibr-147-ae)"))
	item_type = line.get("item_type")
	if item_type and item_type not in codes.ITEM_TYPES:
		issues.append(issue("Error", "EIH-AE-035", f"{p}.item_type", "Item type must be G, S or B (BTAE-13)"))
	if item_type in ("G", "B") and not line.get("commodity_code"):
		issues.append(issue("Error", "EIH-AE-036", f"{p}.commodity_code",
			"Goods (item type G or B) need the HS item classification code (ibr-184-ae / ibr-186-ae)"))

	issues.extend(tax_rules.check_category(category, line.get("tax_rate"), line.get("tax_amount"),
		line.get("exemption_reason"), f"{p}.tax_category"))
	if category == "EXEMPT":
		_exemption_code(line.get("exemption_reason_code"), f"{p}.exemption_reason_code", issues, "ibr-167-ae")
	if category == "REVERSE_CHARGE":
		goods = line.get("rcm_goods_type")
		if goods not in codes.RCM_GOODS_TYPES:
			issues.append(issue("Error", "EIH-AE-047", f"{p}.rcm_goods_type",
				f"Reverse charge lines need the type of goods or services: one of {', '.join(codes.RCM_GOODS_TYPES)} "
				"(ibr-166-ae / ibr-006-ae)"))
		if not line.get("standard_item_id") or (line.get("standard_item_scheme") or "0160") != "0160":
			issues.append(issue("Error", "EIH-AE-048", f"{p}.standard_item_id",
				"Reverse charge lines need the item's standard identifier (GTIN, scheme 0160) (ibr-174-ae)"))
		if not get_path(inv, "customer.tax_id"):
			issues.append(issue("Error", "EIH-AE-049", "customer.tax_id",
				"Reverse charge needs the buyer's TRN (ibr-103-ae)"))


def _exemption_code(code, path, issues, rule):
	if not code:
		issues.append(issue("Error", "EIH-AE-044", path,
			f"Exempt supplies need an exemption reason code: one of {', '.join(codes.EXEMPTION_REASONS)} ({rule})"))
	elif code not in codes.EXEMPTION_REASONS:
		issues.append(issue("Error", "EIH-AE-044", path,
			f"Exemption reason code '{code}' is not in the UAE list ({', '.join(codes.EXEMPTION_REASONS)})"))


def validate(inv):
	issues = []
	doc = inv.get("document") or {}
	_document(inv, issues)
	_party(inv, "supplier", doc, issues)
	_party(inv, "customer", doc, issues)
	if get_path(inv, "references.credit_reason_code") != codes.VOLUME_DISCOUNT:
		issues.extend(validate_credit_note(inv))
	_categories(inv, issues)

	lines = inv.get("lines") or []
	line_sum = ZERO
	for i, line in enumerate(lines):
		line_sum += _d(line.get("net_amount"))
		_line(inv, i, line, issues)
	for i, ac in enumerate(inv.get("allowances_charges") or []):
		p = f"allowances_charges[{i}]"
		if ac.get("tax_category") == "MARGIN_SCHEME":
			issues.append(issue("Error", "EIH-AE-040", f"{p}.tax_category",
				"Document level allowances and charges cannot use MARGIN_SCHEME (ibr-114-ae / ibr-115-ae)"))
		if ac.get("tax_category") == "EXEMPT":
			_exemption_code(ac.get("exemption_reason_code"), f"{p}.exemption_reason_code", issues, "ibr-168-ae / ibr-169-ae")

	totals = inv.get("totals") or {}
	subtotal, tax_total, grand = _d(totals.get("subtotal")), _d(totals.get("tax_total")), _d(totals.get("grand_total"))
	tax_exclusive = _d(totals.get("tax_exclusive"))
	if abs(subtotal - line_sum) > TOL:
		issues.append(issue("Error", "EIH-AE-050", "totals.subtotal",
			f"Subtotal {subtotal} does not equal the sum of line net amounts ({line_sum})"))
	expected_excl = subtotal - _d(totals.get("allowance_total")) + _d(totals.get("charge_total"))
	if abs(tax_exclusive - expected_excl) > TOL:
		issues.append(issue("Error", "EIH-AE-051", "totals.tax_exclusive",
			f"Tax-exclusive amount {tax_exclusive} does not equal subtotal - allowances + charges ({expected_excl})"))
	if abs(grand - (tax_exclusive + tax_total)) > TOL:
		issues.append(issue("Error", "EIH-AE-052", "totals.grand_total",
			f"Grand total {grand} does not equal tax-exclusive amount + tax ({tax_exclusive + tax_total})"))

	breakdown = inv.get("tax_breakdown") or []
	b_taxable = sum((_d(b.get("taxable_amount")) for b in breakdown), ZERO)
	b_tax = sum((_d(b.get("tax_amount")) for b in breakdown), ZERO)
	if not breakdown:
		issues.append(issue("Error", "EIH-AE-053", "tax_breakdown", "At least one tax breakdown is required"))
	if breakdown and abs(b_taxable - tax_exclusive) > TOL:
		issues.append(issue("Error", "EIH-AE-054", "tax_breakdown",
			f"Sum of taxable amounts ({b_taxable}) does not equal the tax-exclusive amount ({tax_exclusive})"))
	if breakdown and abs(b_tax - tax_total) > TOL:
		issues.append(issue("Error", "EIH-AE-055", "tax_breakdown",
			f"Sum of tax breakdown amounts ({b_tax}) does not equal the tax total ({tax_total})"))
	for i, b in enumerate(breakdown):
		taxable, rate, tax = _d(b.get("taxable_amount")), _d(b.get("tax_rate")), _d(b.get("tax_amount"))
		if b.get("tax_category") in tax_rules.NO_TAX_CATEGORIES:
			if tax != 0:
				issues.append(issue("Error", "EIH-AE-056", f"tax_breakdown[{i}].tax_amount",
					f"{b.get('tax_category')} breakdown must carry zero VAT (aligned-ibrp-ae-09-ae / ibr-108-ae)"))
			continue
		# one cent of rounding per line is tolerated when tax is computed line by line
		allowed = TOL * max(1, len(lines))
		if abs(taxable * rate / 100 - tax) > allowed:
			issues.append(issue("Error", "EIH-AE-056", f"tax_breakdown[{i}].tax_amount",
				f"Tax amount {tax} does not equal taxable amount x rate ({(taxable * rate / 100).quantize(TOL)})"))
		if b.get("tax_category") == "EXEMPT":
			_exemption_code(b.get("exemption_reason_code"), f"tax_breakdown[{i}].exemption_reason_code", issues,
				"aligned-ibrp-e-10")
	return issues
