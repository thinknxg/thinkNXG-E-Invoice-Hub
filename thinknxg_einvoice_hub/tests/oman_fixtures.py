"""Oman PINT OM test fixtures (canonical invoices). TEST DATA ONLY.

Party names, VATINs, commercial registrations and invoice numbers are invented.
HS and ISIC codes are taken from the official PINT OM 1.0.1 code lists so that the
generated XML can be checked with the official Schematron.
"""

import copy

SELLER = {
	"legal_name": "Muscat Office Supplies LLC",
	"trading_name": "MOS",
	"tax_id": "OM1100003554",
	"identifier": "1234567",
	"identifier_scheme": "CR",
	"address": {"street": "Way 2317", "additional_street": "Building 192", "address_line": "P.O. Box 192",
		"city": "Muscat", "postal_code": "112", "subdivision": "MO", "country": "OM"},
	"contact": {"name": "Accounts", "phone": "+968 2400 0000", "email": "accounts@example.om"},
}

BUYER = {
	"legal_name": "Sohar Engineering SAOC",
	"tax_id": "OM1100009876",
	"address": {"street": "Industrial Area", "additional_street": "Plot 14", "address_line": "P.O. Box 77",
		"city": "Sohar", "postal_code": "311", "subdivision": "SHRFZ", "country": "OM"},
	"contact": {"name": "Purchasing"},
}

GOODS = {"item_code": "LAP-14", "item_name": "Laptop computer 14 inch", "quantity": 2, "unit_code": "H87",
	"unit_price": 350.250, "item_type": "G", "commodity_code": "847130000002", "industry_code": "465101",
	"tax_category": "STANDARD", "tax_rate": 5}
SERVICE = {"item_code": "SUP-1", "item_name": "On-site IT support (hours)", "quantity": 3, "unit_code": "HUR",
	"unit_price": 12.345, "item_type": "S", "service_type": "81000000", "industry_code": "620101",
	"tax_category": "STANDARD", "tax_rate": 5}


def invoice(**doc):
	inv = {
		"schema_version": "1.0",
		"document": {"document_type": "INVOICE", "invoice_number": "OM-INV-2026-0001", "invoice_date": "2026-11-15",
			"issue_time": "10:30:00", "due_date": "2026-12-15", "currency": "OMR"},
		"supplier": copy.deepcopy(SELLER),
		"customer": copy.deepcopy(BUYER),
		"lines": [copy.deepcopy(GOODS), copy.deepcopy(SERVICE)],
		"payment": {"means_code": "30", "terms": "30 days"},
		"references": {"order_reference": "PO-5521"},
	}
	inv["document"].update(doc)
	return inv


def standard():
	return invoice()


def zero_rated():
	inv = invoice(invoice_number="OM-INV-2026-0002")
	inv["lines"] = [dict(copy.deepcopy(GOODS), item_name="Rice 25 kg", commodity_code="100630000000", industry_code="463001",
		unit_price=9.5, quantity=10, tax_category="ZERO_RATED", tax_rate=0, exemption_reason_code="VATZR-OM-01",
		exemption_reason="Qualifying supply of food items")]
	return inv


def exempt():
	inv = invoice(invoice_number="OM-INV-2026-0003")
	inv["lines"] = [dict(copy.deepcopy(SERVICE), item_name="Residential apartment rent - November", service_type="80000000",
		industry_code="681001", quantity=1, unit_price=450, tax_category="EXEMPT", tax_rate=0,
		exemption_reason_code="VATEX-OM-04", exemption_reason="Rental of properties for residential purposes")]
	return inv


def credit_note(original_uuid):
	inv = invoice(document_type="CREDIT_NOTE", invoice_number="OM-CN-2026-0001")
	inv["document"].pop("due_date")
	inv["lines"] = [dict(copy.deepcopy(GOODS), quantity=1)]
	inv["references"].update({"original_invoice_number": "OM-INV-2026-0001", "original_invoice_date": "2026-11-15",
		"original_invoice_uuid": original_uuid, "credit_reason_code": "CAN", "credit_reason": "One laptop returned"})
	return inv


def foreign_currency():
	inv = invoice(invoice_number="OM-INV-2026-0004", currency="USD", exchange_rate="0.3845")
	inv["lines"] = [dict(copy.deepcopy(SERVICE), unit_price=120, quantity=5)]
	return inv


def b2c():
	inv = invoice(invoice_number="POS-2026-000981")
	inv["customer"] = {}
	inv["extensions"] = {"om": {"b2c": True}}
	inv["lines"] = [dict(copy.deepcopy(GOODS), quantity=1, unit_price=299.990)]
	return inv


def export():
	inv = invoice(invoice_number="OM-EXP-2026-0001")
	inv["customer"] = {"legal_name": "Mumbai Traders Pvt Ltd", "identifier": "AAACM1234X", "identifier_scheme": "OTHID",
		"address": {"street": "Nariman Point", "additional_street": "Tower B", "address_line": "Floor 9", "city": "Mumbai",
			"postal_code": "400021", "country": "IN"}}
	inv["extensions"] = {"om": {"transaction_types": ["FULL_TAX_INVOICE", "EXPORT"], "substitute_participant": "EXPORT"}}
	inv["delivery"] = {"address": {"country": "IN"}}
	inv["lines"] = [dict(copy.deepcopy(GOODS), tax_category="ZERO_RATED", tax_rate=0, exemption_reason_code="VATZR-OM-10",
		exemption_reason="Direct export of goods")]
	return inv


def invalid_supplier_vatin():
	inv = invoice(invoice_number="BAD-1")
	inv["supplier"]["tax_id"] = "OM12345"
	return inv


def missing_buyer():
	inv = invoice(invoice_number="BAD-2")
	inv["customer"] = {"legal_name": "", "address": {"country": "OM"}}
	return inv


def bad_tax():
	inv = invoice(invoice_number="BAD-3")
	inv["lines"][0]["tax_amount"] = 99  # 5% of 700.500 is 35.025
	return inv


SCENARIOS = {
	"standard": standard, "zero_rated": zero_rated, "exempt": exempt, "foreign_currency": foreign_currency,
	"b2c": b2c, "export": export,
}
INVALID = {"invalid_supplier_vatin": invalid_supplier_vatin, "missing_buyer": missing_buyer, "bad_tax": bad_tax}


def self_billing():
	"""Buyer (our company) issues the invoice on behalf of the seller (self-billing agreement)."""
	inv = invoice(document_type="SELF_BILLING_INVOICE", invoice_number="OM-SB-2026-0001")
	inv["supplier"], inv["customer"] = copy.deepcopy(BUYER), copy.deepcopy(SELLER)
	inv["supplier"]["contact"]["phone"] = "+968 2600 0000"
	inv["supplier"]["address"]["subdivision"] = "MO"
	return inv


def allowance_charge():
	inv = invoice(invoice_number="OM-INV-2026-0005")
	inv["allowances_charges"] = [
		{"is_charge": False, "amount": 10.5, "reason": "Loyalty discount", "reason_code": "95", "tax_category": "STANDARD", "tax_rate": 5},
		{"is_charge": True, "amount": 4.25, "reason": "Delivery", "reason_code": "FC", "tax_category": "STANDARD", "tax_rate": 5},
	]
	return inv


SCENARIOS.update({"self_billing": self_billing, "allowance_charge": allowance_charge})
