"""Normalise a canonical invoice: clean codes and dates, derive missing amounts.

The normaliser never overwrites an amount the ERP supplied; it only fills gaps,
so the compliance engine can still detect arithmetic the ERP got wrong.
"""

import copy
from decimal import Decimal

from thinknxg_einvoice_hub.canonical.invoice_schema import CREDIT_TYPES, SCHEMA_VERSION
from thinknxg_einvoice_hub.utils import currency_places, fnum, money, to_decimal, to_iso_date

ZERO = Decimal("0")
DEFAULT_UNIT_CODE = "C62"  # UN/ECE Rec 20 "one"
PARTY_TEXT = ("legal_name", "trading_name", "tax_id", "tin", "endpoint_scheme", "legal_registration_id",
	"legal_registration_type", "legal_registration_authority", "identifier", "identifier_scheme", "uuid")
ADDRESS_TEXT = ("street", "additional_street", "city", "postal_code", "subdivision", "country")


def _text(value):
	return str(value).strip() if value not in (None, "") else None


def _code(value):
	text = _text(value)
	return text.upper().replace(" ", "_").replace("-", "_") if text else None


def _party(party):
	party = dict(party or {})
	for key in PARTY_TEXT:
		if key in party:
			party[key] = _text(party[key])
	if party.get("tax_id"):
		party["tax_id"] = party["tax_id"].replace(" ", "")
	address = dict(party.get("address") or {})
	for key in ADDRESS_TEXT:
		if key in address:
			address[key] = _text(address[key])
	country = address.get("country") or party.get("country")
	if country:
		address["country"] = country.upper()
	party.pop("country", None)
	party["address"] = address
	return party


def _line(index, line, flip, places=2):
	line = dict(line)
	qty = to_decimal(line.get("quantity"), ZERO)
	price = to_decimal(line.get("unit_price"), ZERO)
	discount = to_decimal(line.get("discount_amount"), ZERO)
	net = to_decimal(line.get("net_amount"))
	rate = to_decimal(line.get("tax_rate"), ZERO)
	tax = to_decimal(line.get("tax_amount"))
	if flip:
		qty, price, discount = abs(qty), abs(price), abs(discount)
		net = abs(net) if net is not None else None
		tax = abs(tax) if tax is not None else None
	if net is None:
		net = money(qty * price - discount, places)
	if tax is None:
		tax = money(net * rate / 100, places)
	line.update({
		"line_id": _text(line.get("line_id")) or str(index + 1),
		"quantity": fnum(qty, 6),
		"unit_code": _text(line.get("unit_code")) or DEFAULT_UNIT_CODE,
		"unit_price": fnum(price, 6),
		"price_base_quantity": fnum(line.get("price_base_quantity") or 1, 6),
		"discount_amount": fnum(discount, places),
		"net_amount": fnum(net, places),
		"tax_category": _code(line.get("tax_category")) or ("STANDARD" if rate > 0 else "ZERO_RATED"),
		"tax_rate": fnum(rate, 4),
		"tax_amount": fnum(tax, places),
	})
	return line


def _breakdown(lines, allowances_charges, places=2):
	groups = {}
	for row in lines:
		key = (row["tax_category"], row["tax_rate"])
		g = groups.setdefault(key, {"taxable": ZERO, "tax": ZERO, "reason": None, "code": None})
		g["taxable"] += to_decimal(row["net_amount"], ZERO)
		g["tax"] += to_decimal(row["tax_amount"], ZERO)
		g["reason"] = g["reason"] or row.get("exemption_reason")
		g["code"] = g["code"] or row.get("exemption_reason_code")
	for ac in allowances_charges:
		key = (ac["tax_category"], ac["tax_rate"])
		g = groups.setdefault(key, {"taxable": ZERO, "tax": ZERO, "reason": None, "code": None})
		amount = to_decimal(ac["amount"], ZERO)
		signed = amount if ac.get("is_charge") else -amount
		g["taxable"] += signed
		g["tax"] += money(signed * to_decimal(ac["tax_rate"], ZERO) / 100, places)
	return [
		{
			"tax_category": cat,
			"tax_rate": rate,
			"taxable_amount": fnum(g["taxable"], places),
			"tax_amount": fnum(g["tax"], places),
			"exemption_reason": g["reason"],
			"exemption_reason_code": g["code"],
		}
		for (cat, rate), g in sorted(groups.items())
	]


def normalize(inv):
	inv = copy.deepcopy(inv)
	inv.setdefault("schema_version", SCHEMA_VERSION)

	doc = inv.setdefault("document", {})
	doc["document_type"] = _code(doc.get("document_type")) or "INVOICE"
	doc["invoice_kind"] = _code(doc.get("invoice_kind")) or "TAX"
	doc["direction"] = _code(doc.get("direction")) or "OUTBOUND"
	doc["invoice_number"] = _text(doc.get("invoice_number"))
	doc["currency"] = (_text(doc.get("currency")) or "").upper() or None
	doc["tax_currency"] = (_text(doc.get("tax_currency")) or "").upper() or None
	doc["exchange_rate"] = fnum(doc.get("exchange_rate") or 1, 6)
	for key in ("invoice_date", "due_date", "tax_point_date"):
		if doc.get(key) not in (None, ""):
			doc[key] = to_iso_date(doc[key]) or doc[key]

	places = currency_places(doc["currency"])
	for key in ("uuid", "issue_time"):
		if key in doc:
			doc[key] = _text(doc[key])

	inv["supplier"] = _party(inv.get("supplier"))
	inv["customer"] = _party(inv.get("customer"))

	raw_lines = [l for l in (inv.get("lines") or []) if isinstance(l, dict)]
	totals = dict(inv.get("totals") or {})
	flip = doc["document_type"] in CREDIT_TYPES and (
		(to_decimal(totals.get("grand_total"), ZERO) < 0)
		or any(to_decimal(l.get("quantity"), ZERO) < 0 for l in raw_lines)
	)
	lines = [_line(i, l, flip, places) for i, l in enumerate(raw_lines)]
	inv["lines"] = lines

	acs = []
	for ac in inv.get("allowances_charges") or []:
		ac = dict(ac)
		rate = to_decimal(ac.get("tax_rate"), ZERO)
		ac.update({
			"is_charge": bool(ac.get("is_charge")),
			"amount": fnum(abs(to_decimal(ac.get("amount"), ZERO)), places),
			"tax_category": _code(ac.get("tax_category")) or ("STANDARD" if rate > 0 else "ZERO_RATED"),
			"tax_rate": fnum(rate, 4),
		})
		acs.append(ac)
	inv["allowances_charges"] = acs

	if not inv.get("tax_breakdown"):
		inv["tax_breakdown"] = _breakdown(lines, acs, places)
	else:
		for row in inv["tax_breakdown"]:
			row["tax_category"] = _code(row.get("tax_category"))
			for key, dp in (("tax_rate", 4), ("taxable_amount", places), ("tax_amount", places)):
				val = to_decimal(row.get(key), ZERO)
				row[key] = fnum(abs(val) if flip else val, dp)

	def given(key):
		val = to_decimal(totals.get(key))
		return abs(val) if (val is not None and flip) else val

	subtotal = given("subtotal")
	if subtotal is None:
		subtotal = sum((to_decimal(l["net_amount"], ZERO) for l in lines), ZERO)
	allowance = given("allowance_total")
	if allowance is None:
		allowance = sum((to_decimal(a["amount"], ZERO) for a in acs if not a["is_charge"]), ZERO)
	charge = given("charge_total")
	if charge is None:
		charge = sum((to_decimal(a["amount"], ZERO) for a in acs if a["is_charge"]), ZERO)
	tax_exclusive = given("tax_exclusive")
	if tax_exclusive is None:
		tax_exclusive = subtotal - allowance + charge
	tax_total = given("tax_total")
	if tax_total is None:
		tax_total = sum((to_decimal(b["tax_amount"], ZERO) for b in inv["tax_breakdown"]), ZERO)
	grand = given("grand_total")
	if grand is None:
		grand = tax_exclusive + tax_total
	prepaid = given("prepaid_amount") or ZERO
	rounding = to_decimal(totals.get("rounding_amount"), ZERO)
	payable = given("payable_amount")
	if payable is None:
		payable = grand - prepaid + rounding
	inv["totals"] = {
		"subtotal": fnum(subtotal, places),
		"allowance_total": fnum(allowance, places),
		"charge_total": fnum(charge, places),
		"tax_exclusive": fnum(tax_exclusive, places),
		"tax_total": fnum(tax_total, places),
		"grand_total": fnum(grand, places),
		"prepaid_amount": fnum(prepaid, places),
		"rounding_amount": fnum(rounding, places),
		"payable_amount": fnum(payable, places),
	}

	refs = inv.setdefault("references", {})
	if refs.get("original_invoice_date"):
		refs["original_invoice_date"] = to_iso_date(refs["original_invoice_date"]) or refs["original_invoice_date"]
	return inv
