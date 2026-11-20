"""UAE PINT AE 1.0.5 test fixtures (canonical invoices). TEST DATA ONLY.

Party names, TRNs, trade licence numbers, IBANs, GTINs and invoice numbers are
invented. TRNs follow the shape the official rules check (15 digits, starting with
1, ending with 03, ibr-132-ae); code values (credit reasons, exemption codes, RCM
goods types, frequencies) are taken from the official PINT AE 1.0.5 code lists so
the generated XML can be checked with the official Schematron.
"""

import copy

SELLER = {
	"legal_name": "ABC Trading LLC",
	"trading_name": "ABC",
	"tax_id": "100000000000003",
	"legal_registration_id": "CN-1234567",
	"legal_registration_type": "TL",
	"legal_registration_authority": "Dubai Department of Economy and Tourism",
	"address": {"street": "Sheikh Zayed Road", "city": "Dubai", "postal_code": "00000", "subdivision": "DXB",
		"country": "AE"},
	"contact": {"name": "Accounts", "phone": "+971 4 000 0000", "email": "accounts@example.ae"},
}

BUYER = {
	"legal_name": "XYZ LLC",
	"tax_id": "100234567800003",
	"address": {"street": "Corniche Road", "city": "Abu Dhabi", "subdivision": "AUH", "country": "AE"},
}

FOREIGN_BUYER = {
	"legal_name": "Northwind Imports Inc",
	"legal_registration_id": "P1234567",
	"legal_registration_type": "PAS",
	"legal_registration_authority": "US",
	"address": {"street": "1 Harbor Way", "city": "Seattle", "postal_code": "98101", "subdivision": "WA",
		"country": "US"},
}

GOODS = {"item_code": "LAP-14", "item_name": "Laptop computer 14 inch", "description": "Laptop computer, 14 inch, 16 GB",
	"quantity": 2, "unit_code": "H87", "unit_price": 3500, "item_type": "G", "commodity_code": "847130",
	"tax_category": "STANDARD", "tax_rate": 5}
SERVICE = {"item_code": "CONS", "item_name": "Consulting", "quantity": 10, "unit_code": "HUR", "unit_price": 450,
	"item_type": "S", "tax_category": "STANDARD", "tax_rate": 5}


def with_service_codes(inv, code="998311"):
	"""Add BTAE-17 to service lines (needed only by ASPs still validating with PINT AE 1.0.4)."""
	for line in inv["lines"]:
		if line.get("item_type") in ("S", "B"):
			line["service_accounting_code"] = code
	return inv
PAYMENT = {"means_code": "30", "iban": "AE070331234567890123456", "account_name": "ABC Trading LLC",
	"terms": "Net 30"}


def invoice(**doc):
	inv = {
		"schema_version": "1.0",
		"document": {"document_type": "INVOICE", "invoice_kind": "TAX", "invoice_number": "AE-INV-2026-0001",
			"invoice_date": "2026-11-15", "due_date": "2026-12-15", "currency": "AED",
			"transaction_type_flags": "00000000"},
		"supplier": copy.deepcopy(SELLER),
		"customer": copy.deepcopy(BUYER),
		"lines": [copy.deepcopy(GOODS), copy.deepcopy(SERVICE)],
		"payment": copy.deepcopy(PAYMENT),
		"references": {"order_reference": "PO-778"},
	}
	inv["document"].update(doc)
	return inv


def standard():
	return invoice()


def zero_rated():
	inv = invoice(invoice_number="AE-INV-2026-0002")
	inv["lines"] = [dict(GOODS, tax_category="ZERO_RATED", tax_rate=0)]
	return inv


def mixed():
	"""Standard, zero-rated and exempt lines on one tax invoice."""
	inv = invoice(invoice_number="AE-INV-2026-0003")
	inv["lines"] = [copy.deepcopy(SERVICE), dict(GOODS, tax_category="ZERO_RATED", tax_rate=0),
		{"item_code": "RENT-11", "item_name": "Residential apartment rent, November", "quantity": 1, "unit_code": "MON",
			"unit_price": 8000, "item_type": "S", "tax_category": "EXEMPT", "tax_rate": 0,
			"exemption_reason_code": "DL8.46.2", "exemption_reason": "Supply of residential units"}]
	return inv


def out_of_scope():
	"""480 - invoice out of scope of VAT (only EXEMPT / OUT_OF_SCOPE allowed, buyer legal registration required)."""
	inv = invoice(invoice_number="AE-INV-2026-0004", invoice_kind="COMMERCIAL")
	inv["customer"].update(legal_registration_id="CN-7654321", legal_registration_type="TL",
		legal_registration_authority="Abu Dhabi Department of Economic Development")
	inv["lines"] = [{"item_code": "DON", "item_name": "Sponsorship contribution", "quantity": 1, "unit_code": "C62",
		"unit_price": 5000, "item_type": "S", "tax_category": "OUT_OF_SCOPE", "tax_rate": 0}]
	return inv


def reverse_charge():
	inv = invoice(invoice_number="AE-INV-2026-0005")
	inv["lines"] = [{"item_code": "PHN-1", "item_name": "Mobile phones, wholesale", "quantity": 100, "unit_code": "H87",
		"unit_price": 900, "item_type": "G", "commodity_code": "851713", "standard_item_id": "04012345000017",
		"rcm_goods_type": "DL8.48.8.2", "tax_category": "REVERSE_CHARGE", "tax_rate": 5, "tax_amount": 0}]
	return inv


def margin_scheme():
	inv = invoice(invoice_number="AE-INV-2026-0006", transaction_type_flags="00100000")
	inv["lines"] = [{"item_code": "CAR-USED", "item_name": "Used vehicle (margin scheme)", "quantity": 1,
		"unit_code": "H87", "unit_price": 45000, "item_type": "G", "commodity_code": "870323",
		"tax_category": "MARGIN_SCHEME", "tax_rate": 5, "tax_amount": 0}]
	return inv


def foreign_currency():
	inv = invoice(invoice_number="AE-INV-2026-0007", currency="USD", exchange_rate="3.6725")
	inv["lines"] = [dict(GOODS, unit_price=950.5)]
	return inv


def export():
	"""Zero-rated export to a buyer outside the network: predefined endpoint 9900000099 is used."""
	inv = invoice(invoice_number="AE-INV-2026-0008", currency="USD", exchange_rate="3.6725",
		transaction_type_flags="00000001")
	inv["customer"] = copy.deepcopy(FOREIGN_BUYER)
	inv["delivery"] = {"date": "2026-11-14", "address": dict(FOREIGN_BUYER["address"])}
	inv["lines"] = [dict(GOODS, tax_category="ZERO_RATED", tax_rate=0)]
	return inv


def allowance_charge():
	inv = invoice(invoice_number="AE-INV-2026-0009")
	inv["lines"][0]["discount_amount"] = 200
	inv["lines"][0]["net_amount"] = 6800
	inv["allowances_charges"] = [
		{"is_charge": False, "amount": 100, "reason": "Loyalty discount", "tax_category": "STANDARD", "tax_rate": 5},
		{"is_charge": True, "amount": 50, "reason": "Delivery", "tax_category": "STANDARD", "tax_rate": 5},
	]
	return inv


def summary():
	inv = invoice(invoice_number="AE-INV-2026-0010", transaction_type_flags="00010000",
		invoice_period={"start_date": "2026-10-01", "end_date": "2026-10-31", "frequency_code": "MTH"})
	inv["lines"] = [copy.deepcopy(SERVICE)]
	return inv


def credit_note():
	inv = invoice(document_type="CREDIT_NOTE", invoice_number="AE-CN-2026-0001")
	inv["references"] = {"original_invoice_number": "AE-INV-2026-0001", "original_invoice_date": "2026-11-15",
		"credit_reason_code": "DL8.61.1.D", "credit_reason": "Goods returned"}
	inv["lines"] = [dict(GOODS, quantity=1)]
	return inv


def volume_discount_credit_note():
	inv = invoice(document_type="CREDIT_NOTE", invoice_number="AE-CN-2026-0002")
	inv["references"] = {"credit_reason_code": "VD", "credit_reason": "Volume discount, Q4"}
	inv["lines"] = [{"item_code": "VD-Q4", "item_name": "Volume discount Q4", "quantity": 1, "unit_code": "C62",
		"unit_price": 1000, "item_type": "S", "tax_category": "STANDARD", "tax_rate": 5}]
	return inv


def commercial_credit_note():
	inv = out_of_scope()
	inv["document"].update(document_type="CREDIT_NOTE", invoice_number="AE-CN-2026-0003")
	inv["references"] = {"original_invoice_number": "AE-INV-2026-0004", "original_invoice_date": "2026-11-15",
		"credit_reason_code": "DL8.61.1.A"}
	return inv


def self_billing():
	inv = invoice(document_type="SELF_BILLING_INVOICE", invoice_number="AE-SB-2026-0001")
	inv["lines"] = [copy.deepcopy(SERVICE)]
	return inv


def self_billing_credit_note():
	inv = invoice(document_type="SELF_BILLING_CREDIT_NOTE", invoice_number="AE-SBCN-2026-0001")
	inv["references"] = {"original_invoice_number": "AE-SB-2026-0001", "original_invoice_date": "2026-11-15",
		"credit_reason_code": "DL8.61.1.C"}
	inv["lines"] = [dict(SERVICE, quantity=2)]
	return inv


SCENARIOS = {
	"standard": standard,
	"zero_rated": zero_rated,
	"mixed": mixed,
	"out_of_scope": out_of_scope,
	"reverse_charge": reverse_charge,
	"margin_scheme": margin_scheme,
	"foreign_currency": foreign_currency,
	"export": export,
	"allowance_charge": allowance_charge,
	"summary": summary,
	"credit_note": credit_note,
	"volume_discount_credit_note": volume_discount_credit_note,
	"commercial_credit_note": commercial_credit_note,
	"self_billing": self_billing,
	"self_billing_credit_note": self_billing_credit_note,
}
