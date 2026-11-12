"""Pre-submission validation for UAE PINT AE.

These are the hub's own baseline checks (rule IDs ``EIH-AE-*``), run before a
document leaves the platform so that data problems are reported to the ERP
immediately. They do not replace the official PINT AE Schematron, which the
Accredited Service Provider applies on submission.
"""

import re
from decimal import Decimal

from thinknxg_einvoice_hub.canonical.credit_note_schema import validate_credit_note
from thinknxg_einvoice_hub.compliance.uae import tax_rules
from thinknxg_einvoice_hub.utils import get_path, issue, to_decimal, to_iso_date

ZERO = Decimal("0")
TOL = Decimal("0.01")
TRN_RE = re.compile(r"^\d{15}$")
TIN_RE = re.compile(r"^\d{10}$")
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
FLAGS_RE = re.compile(r"^[01]{8}$")
EMIRATES = ("AUH", "DXB", "SHJ", "AJM", "UAQ", "RAK", "FUJ")


def _d(value):
	return to_decimal(value, ZERO)


def _party(inv, role, kind, issues):
	party = inv.get(role) or {}
	addr = party.get("address") or {}
	label = role.capitalize()
	country = addr.get("country")
	is_ae = country == "AE"
	tax_invoice = kind == "TAX"

	if not party.get("legal_name"):
		issues.append(issue("Error", "EIH-AE-010", f"{role}.legal_name", f"{label} legal name is required"))
	if not country or len(country) != 2:
		issues.append(issue("Error", "EIH-AE-011", f"{role}.address.country",
			f"{label} country must be an ISO 3166-1 alpha-2 code"))
	for field in ("street", "city"):
		if not addr.get(field):
			issues.append(issue("Error", "EIH-AE-012", f"{role}.address.{field}", f"{label} address {field} is required"))
	if is_ae:
		if not addr.get("subdivision"):
			issues.append(issue("Error", "EIH-AE-013", f"{role}.address.subdivision",
				f"{label} emirate code is required for UAE addresses"))
		elif addr["subdivision"].upper() not in EMIRATES:
			issues.append(issue("Warning", "EIH-AE-014", f"{role}.address.subdivision",
				f"{label} emirate '{addr['subdivision']}' is not one of {', '.join(EMIRATES)}"))

	trn = party.get("tax_id")
	if role == "supplier" and tax_invoice and not trn:
		issues.append(issue("Error", "EIH-AE-015", "supplier.tax_id", "Supplier TRN is required on a tax invoice"))
	if trn and is_ae and not TRN_RE.match(trn):
		issues.append(issue("Error", "EIH-AE-016", f"{role}.tax_id", f"{label} TRN must be 15 digits"))

	tin = party.get("tin")
	if not tin:
		level = "Error" if role == "supplier" or is_ae else "Warning"
		issues.append(issue(level, "EIH-AE-017", f"{role}.tin",
			f"{label} electronic address (TIN) is missing; it is needed to route the invoice on the network"))
	elif (party.get("endpoint_scheme") or "0235") == "0235" and not TIN_RE.match(tin):
		issues.append(issue("Error", "EIH-AE-018", f"{role}.tin", f"{label} TIN must be 10 digits"))


def validate(inv):
	issues = []
	doc = inv.get("document") or {}
	kind = doc.get("invoice_kind") or "TAX"
	currency = doc.get("currency") or ""

	if not doc.get("invoice_number"):
		issues.append(issue("Error", "EIH-AE-001", "document.invoice_number", "Invoice number is required"))
	if not to_iso_date(doc.get("invoice_date")):
		issues.append(issue("Error", "EIH-AE-002", "document.invoice_date", "Invoice date must be a valid date"))
	if doc.get("due_date") and not to_iso_date(doc["due_date"]):
		issues.append(issue("Error", "EIH-AE-003", "document.due_date", "Due date must be a valid date"))
	if not CURRENCY_RE.match(currency):
		issues.append(issue("Error", "EIH-AE-004", "document.currency", "Currency must be an ISO 4217 code"))
	if not FLAGS_RE.match(doc.get("transaction_type_flags") or ""):
		issues.append(issue("Error", "EIH-AE-005", "document.transaction_type_flags",
			"Transaction type flags must be 8 binary digits, e.g. 00000000"))
	if currency and currency != "AED" and _d(doc.get("exchange_rate")) in (ZERO, Decimal("1")):
		issues.append(issue("Warning", "EIH-AE-006", "document.exchange_rate",
			"Invoice is not in AED; provide the exchange rate so the tax amount can be reported in AED"))
	if not doc.get("due_date") and not get_path(inv, "payment.terms"):
		issues.append(issue("Warning", "EIH-AE-007", "document.due_date", "Provide a payment due date or payment terms"))

	_party(inv, "supplier", kind, issues)
	_party(inv, "customer", kind, issues)
	issues.extend(validate_credit_note(inv))

	lines = inv.get("lines") or []
	line_sum = ZERO
	for i, line in enumerate(lines):
		p = f"lines[{i}]"
		qty, price, disc = _d(line.get("quantity")), _d(line.get("unit_price")), _d(line.get("discount_amount"))
		net = _d(line.get("net_amount"))
		base = _d(line.get("price_base_quantity")) or Decimal("1")
		line_sum += net
		if qty == 0:
			issues.append(issue("Error", "EIH-AE-030", f"{p}.quantity", "Quantity must not be zero"))
		if price < 0:
			issues.append(issue("Error", "EIH-AE-031", f"{p}.unit_price", "Unit price must not be negative"))
		if not line.get("unit_code"):
			issues.append(issue("Error", "EIH-AE-032", f"{p}.unit_code", "Unit of measure code is required"))
		if not line.get("item_name") and not line.get("description"):
			issues.append(issue("Error", "EIH-AE-033", f"{p}.item_name", "Item name is required"))
		expected = qty * price / base - disc
		if abs(expected - net) > TOL:
			issues.append(issue("Error", "EIH-AE-034", f"{p}.net_amount",
				f"Line net amount {net} does not equal quantity x unit price - discount ({expected.quantize(TOL)})"))
		issues.extend(tax_rules.check_category(line.get("tax_category"), line.get("tax_rate"),
			line.get("tax_amount"), line.get("exemption_reason"), f"{p}.tax_category"))

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
		# one cent of rounding per line is tolerated when tax is computed line by line
		allowed = TOL * max(1, len(lines))
		if abs(taxable * rate / 100 - tax) > allowed:
			issues.append(issue("Error", "EIH-AE-056", f"tax_breakdown[{i}].tax_amount",
				f"Tax amount {tax} does not equal taxable amount x rate ({(taxable * rate / 100).quantize(TOL)})"))
	return issues
