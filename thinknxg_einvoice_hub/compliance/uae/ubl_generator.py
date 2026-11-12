"""Canonical invoice <-> UBL 2.1 Invoice / CreditNote in the PINT AE layout."""

from decimal import Decimal

from thinknxg_einvoice_hub.compliance.shared.xml import (
	CREDIT_NOTE_NS,
	INVOICE_NS,
	UBL_NS,
	attr_of,
	cac,
	cbc,
	parse_xml,
	render_document,
	text_of,
)
from thinknxg_einvoice_hub.compliance.uae import tax_rules
from thinknxg_einvoice_hub.exceptions import PermanentError
from thinknxg_einvoice_hub.utils import money, to_decimal

ZERO = Decimal("0")

# (document_type, invoice_kind) -> UNCL 1001 code used by PINT AE
TYPE_CODES = {
	("INVOICE", "TAX"): "380",
	("INVOICE", "COMMERCIAL"): "480",
	("CREDIT_NOTE", "TAX"): "381",
	("CREDIT_NOTE", "COMMERCIAL"): "81",
	("SELF_BILLING_INVOICE", "TAX"): "389",
	("SELF_BILLING_INVOICE", "COMMERCIAL"): "389",
	("SELF_BILLING_CREDIT_NOTE", "TAX"): "261",
	("SELF_BILLING_CREDIT_NOTE", "COMMERCIAL"): "261",
}
CODE_TYPES = {
	"380": ("INVOICE", "TAX"),
	"480": ("INVOICE", "COMMERCIAL"),
	"381": ("CREDIT_NOTE", "TAX"),
	"81": ("CREDIT_NOTE", "COMMERCIAL"),
	"389": ("SELF_BILLING_INVOICE", "TAX"),
	"261": ("SELF_BILLING_CREDIT_NOTE", "TAX"),
}
CREDIT_TYPES = ("CREDIT_NOTE", "SELF_BILLING_CREDIT_NOTE")
SELF_BILLING = ("SELF_BILLING_INVOICE", "SELF_BILLING_CREDIT_NOTE")


def _amt(value):
	return f"{money(value) or ZERO:.2f}"


def _num(value):
	d = to_decimal(value, ZERO)
	text = format(d.normalize(), "f")
	return text if text not in ("-0", "") else "0"


def _address(tag, addr):
	addr = addr or {}
	return cac(tag,
		cbc("StreetName", addr.get("street")),
		cbc("AdditionalStreetName", addr.get("additional_street")),
		cbc("CityName", addr.get("city")),
		cbc("PostalZone", addr.get("postal_code")),
		cbc("CountrySubentity", addr.get("subdivision")),
		cac("Country", cbc("IdentificationCode", addr.get("country"))),
	)


def _party(party, default_scheme):
	party = party or {}
	contact = party.get("contact") or {}
	tax_scheme = None
	if party.get("tax_id"):
		tax_scheme = cac("PartyTaxScheme", cbc("CompanyID", party["tax_id"]), cac("TaxScheme", cbc("ID", "VAT")))
	return cac("Party",
		cbc("EndpointID", party.get("tin"), schemeID=party.get("endpoint_scheme") or default_scheme),
		cac("PartyIdentification", cbc("ID", party.get("identifier"))),
		cac("PartyName", cbc("Name", party.get("trading_name"))),
		_address("PostalAddress", party.get("address")),
		tax_scheme,
		cac("PartyLegalEntity",
			cbc("RegistrationName", party.get("legal_name")),
			cbc("CompanyID", party.get("legal_registration_id"), schemeAgencyID=party.get("legal_registration_type")),
		),
		cac("Contact",
			cbc("Name", contact.get("name")),
			cbc("Telephone", contact.get("phone")),
			cbc("ElectronicMail", contact.get("email")),
		),
	)


def _tax_category(tag, category, rate, reason=None, reason_code=None):
	return cac(tag,
		cbc("ID", tax_rules.category_code(category)),
		cbc("Percent", None if category == "OUT_OF_SCOPE" else _num(rate)),
		cbc("TaxExemptionReasonCode", reason_code),
		cbc("TaxExemptionReason", reason),
		cac("TaxScheme", cbc("ID", "VAT")),
	)


def _line(line, currency, credit):
	discount = to_decimal(line.get("discount_amount"), ZERO)
	name = line.get("item_name") or line.get("description")
	description = line.get("description") if line.get("description") != name else None
	base = to_decimal(line.get("price_base_quantity"), Decimal("1"))
	return cac("CreditNoteLine" if credit else "InvoiceLine",
		cbc("ID", line.get("line_id")),
		cbc("Note", line.get("note")),
		cbc("CreditedQuantity" if credit else "InvoicedQuantity", _num(line.get("quantity")), unitCode=line.get("unit_code")),
		cbc("LineExtensionAmount", _amt(line.get("net_amount")), currencyID=currency),
		cac("AllowanceCharge",
			cbc("ChargeIndicator", "false"),
			cbc("AllowanceChargeReason", "Discount"),
			cbc("Amount", _amt(discount), currencyID=currency),
		) if discount > 0 else None,
		cac("Item",
			cbc("Description", description),
			cbc("Name", name),
			cac("SellersItemIdentification", cbc("ID", line.get("item_code"))),
			cac("CommodityClassification", cbc("ItemClassificationCode", line.get("commodity_code"), listID="HS")),
			_tax_category("ClassifiedTaxCategory", line.get("tax_category"), line.get("tax_rate")),
		),
		cac("Price",
			cbc("PriceAmount", _num(line.get("unit_price")), currencyID=currency),
			cbc("BaseQuantity", _num(base), unitCode=line.get("unit_code")) if base != 1 else None,
		),
	)


def build(inv, profile):
	"""Render a normalised canonical invoice as PINT AE UBL XML."""
	doc = inv.get("document") or {}
	totals = inv.get("totals") or {}
	refs = inv.get("references") or {}
	payment = inv.get("payment") or {}
	delivery = inv.get("delivery") or {}
	doc_type = doc.get("document_type")
	kind = doc.get("invoice_kind") or "TAX"
	type_code = TYPE_CODES.get((doc_type, kind))
	if not type_code:
		raise PermanentError(f"Document type {doc_type}/{kind} is not supported by PINT AE")
	credit = doc_type in CREDIT_TYPES
	selfbilling = doc_type in SELF_BILLING
	currency = doc.get("currency")
	tax_currency = doc.get("tax_currency") or profile.get("default_currency") or currency
	scheme = profile.get("endpoint_scheme")

	children = [
		cbc("CustomizationID", profile["selfbilling_customization_id" if selfbilling else "customization_id"]),
		cbc("ProfileID", profile["selfbilling_profile_id" if selfbilling else "profile_id"]),
		cbc("ProfileExecutionID", doc.get("transaction_type_flags")),
		cbc("ID", doc.get("invoice_number")),
		cbc("IssueDate", doc.get("invoice_date")),
	]
	if credit:
		children += [cbc("TaxPointDate", doc.get("tax_point_date")), cbc("CreditNoteTypeCode", type_code),
			cbc("Note", doc.get("notes"))]
	else:
		children += [cbc("DueDate", doc.get("due_date")), cbc("InvoiceTypeCode", type_code),
			cbc("Note", doc.get("notes")), cbc("TaxPointDate", doc.get("tax_point_date"))]
	children += [
		cbc("DocumentCurrencyCode", currency),
		cbc("TaxCurrencyCode", tax_currency if tax_currency != currency else None),
		cbc("BuyerReference", doc.get("buyer_reference")),
		cac("OrderReference", cbc("ID", refs.get("order_reference"))),
		cac("BillingReference", cac("InvoiceDocumentReference",
			cbc("ID", refs.get("original_invoice_number")),
			cbc("IssueDate", refs.get("original_invoice_date")),
		)),
		cac("ContractDocumentReference", cbc("ID", refs.get("contract_reference"))),
	]
	for att in inv.get("attachments") or []:
		children.append(cac("AdditionalDocumentReference",
			cbc("ID", att.get("id") or att.get("filename")),
			cbc("DocumentDescription", att.get("description")),
			cac("Attachment", cbc("EmbeddedDocumentBinaryObject", att.get("content_base64"),
				mimeCode=att.get("mime_type"), filename=att.get("filename"))),
		))
	children += [
		cac("AccountingSupplierParty", _party(inv.get("supplier"), scheme)),
		cac("AccountingCustomerParty", _party(inv.get("customer"), scheme)),
		cac("Delivery",
			cbc("ActualDeliveryDate", delivery.get("date")),
			cac("DeliveryLocation", _address("Address", delivery.get("address"))),
		),
	]
	if payment.get("means_code") or payment.get("iban") or (credit and doc.get("due_date")):
		children.append(cac("PaymentMeans",
			cbc("PaymentMeansCode", payment.get("means_code") or "1"),
			cbc("PaymentDueDate", doc.get("due_date")) if credit else None,
			cac("PayeeFinancialAccount", cbc("ID", payment.get("iban")), cbc("Name", payment.get("account_name"))),
		))
	children.append(cac("PaymentTerms", cbc("Note", payment.get("terms"))))
	for ac in inv.get("allowances_charges") or []:
		children.append(cac("AllowanceCharge",
			cbc("ChargeIndicator", "true" if ac.get("is_charge") else "false"),
			cbc("AllowanceChargeReason", ac.get("reason")),
			cbc("Amount", _amt(ac.get("amount")), currencyID=currency),
			_tax_category("TaxCategory", ac.get("tax_category"), ac.get("tax_rate")),
		))

	tax_total = cac("TaxTotal", cbc("TaxAmount", _amt(totals.get("tax_total")), currencyID=currency))
	for row in inv.get("tax_breakdown") or []:
		tax_total.add(cac("TaxSubtotal",
			cbc("TaxableAmount", _amt(row.get("taxable_amount")), currencyID=currency),
			cbc("TaxAmount", _amt(row.get("tax_amount")), currencyID=currency),
			_tax_category("TaxCategory", row.get("tax_category"), row.get("tax_rate"),
				row.get("exemption_reason"), row.get("exemption_reason_code")),
		))
	children.append(tax_total)
	if tax_currency and tax_currency != currency:
		rate = to_decimal(doc.get("exchange_rate"), Decimal("1"))
		converted = to_decimal(totals.get("tax_total"), ZERO) * rate
		children.append(cac("TaxTotal", cbc("TaxAmount", _amt(converted), currencyID=tax_currency)))

	def optional(name, key, nonzero_only=True):
		val = to_decimal(totals.get(key), ZERO)
		return cbc(name, _amt(val), currencyID=currency) if (val != 0 or not nonzero_only) else None

	children.append(cac("LegalMonetaryTotal",
		cbc("LineExtensionAmount", _amt(totals.get("subtotal")), currencyID=currency),
		cbc("TaxExclusiveAmount", _amt(totals.get("tax_exclusive")), currencyID=currency),
		cbc("TaxInclusiveAmount", _amt(totals.get("grand_total")), currencyID=currency),
		optional("AllowanceTotalAmount", "allowance_total"),
		optional("ChargeTotalAmount", "charge_total"),
		optional("PrepaidAmount", "prepaid_amount"),
		optional("PayableRoundingAmount", "rounding_amount"),
		cbc("PayableAmount", _amt(totals.get("payable_amount")), currencyID=currency),
	))
	children += [_line(line, currency, credit) for line in inv.get("lines") or []]

	if credit:
		return render_document("CreditNote", CREDIT_NOTE_NS, children)
	return render_document("Invoice", INVOICE_NS, children)


# ---------------------------------------------------------------------- inbound
def _parse_party(node):
	if node is None:
		return {"address": {}}
	addr = node.find("cac:PostalAddress", UBL_NS)
	return {
		"legal_name": text_of(node, "cac:PartyLegalEntity/cbc:RegistrationName") or text_of(node, "cac:PartyName/cbc:Name"),
		"trading_name": text_of(node, "cac:PartyName/cbc:Name"),
		"tax_id": text_of(node, "cac:PartyTaxScheme/cbc:CompanyID"),
		"tin": text_of(node, "cbc:EndpointID"),
		"endpoint_scheme": attr_of(node, "cbc:EndpointID", "schemeID"),
		"legal_registration_id": text_of(node, "cac:PartyLegalEntity/cbc:CompanyID"),
		"legal_registration_type": attr_of(node, "cac:PartyLegalEntity/cbc:CompanyID", "schemeAgencyID"),
		"address": {
			"street": text_of(addr, "cbc:StreetName"),
			"additional_street": text_of(addr, "cbc:AdditionalStreetName"),
			"city": text_of(addr, "cbc:CityName"),
			"postal_code": text_of(addr, "cbc:PostalZone"),
			"subdivision": text_of(addr, "cbc:CountrySubentity"),
			"country": text_of(addr, "cac:Country/cbc:IdentificationCode"),
		},
		"contact": {
			"name": text_of(node, "cac:Contact/cbc:Name"),
			"phone": text_of(node, "cac:Contact/cbc:Telephone"),
			"email": text_of(node, "cac:Contact/cbc:ElectronicMail"),
		},
	}


def parse(content):
	"""Parse a UBL Invoice / CreditNote into an (un-normalised) canonical invoice."""
	root = parse_xml(content)
	local = root.tag.rsplit("}", 1)[-1]
	if local not in ("Invoice", "CreditNote"):
		raise PermanentError(f"Unsupported document root <{local}>; expected Invoice or CreditNote")
	credit = local == "CreditNote"
	type_code = text_of(root, "cbc:CreditNoteTypeCode" if credit else "cbc:InvoiceTypeCode")
	doc_type, kind = CODE_TYPES.get(type_code or "", ("CREDIT_NOTE" if credit else "INVOICE", "TAX"))
	currency = text_of(root, "cbc:DocumentCurrencyCode")

	lines = []
	for node in root.findall("cac:CreditNoteLine" if credit else "cac:InvoiceLine", UBL_NS):
		qty_path = "cbc:CreditedQuantity" if credit else "cbc:InvoicedQuantity"
		code = text_of(node, "cac:Item/cac:ClassifiedTaxCategory/cbc:ID")
		lines.append({
			"line_id": text_of(node, "cbc:ID"),
			"item_code": text_of(node, "cac:Item/cac:SellersItemIdentification/cbc:ID"),
			"item_name": text_of(node, "cac:Item/cbc:Name"),
			"description": text_of(node, "cac:Item/cbc:Description"),
			"quantity": text_of(node, qty_path),
			"unit_code": attr_of(node, qty_path, "unitCode"),
			"unit_price": text_of(node, "cac:Price/cbc:PriceAmount"),
			"price_base_quantity": text_of(node, "cac:Price/cbc:BaseQuantity"),
			"discount_amount": text_of(node, "cac:AllowanceCharge/cbc:Amount"),
			"net_amount": text_of(node, "cbc:LineExtensionAmount"),
			"tax_category": tax_rules.category_from_code(code) or code,
			"tax_rate": text_of(node, "cac:Item/cac:ClassifiedTaxCategory/cbc:Percent") or 0,
			"commodity_code": text_of(node, "cac:Item/cac:CommodityClassification/cbc:ItemClassificationCode"),
		})

	breakdown = []
	tax_total = None
	for total in root.findall("cac:TaxTotal", UBL_NS):
		if attr_of(total, "cbc:TaxAmount", "currencyID") not in (None, currency):
			continue  # tax amount in accounting currency
		tax_total = text_of(total, "cbc:TaxAmount")
		for sub in total.findall("cac:TaxSubtotal", UBL_NS):
			code = text_of(sub, "cac:TaxCategory/cbc:ID")
			breakdown.append({
				"tax_category": tax_rules.category_from_code(code) or code,
				"tax_rate": text_of(sub, "cac:TaxCategory/cbc:Percent") or 0,
				"taxable_amount": text_of(sub, "cbc:TaxableAmount"),
				"tax_amount": text_of(sub, "cbc:TaxAmount"),
				"exemption_reason": text_of(sub, "cac:TaxCategory/cbc:TaxExemptionReason"),
				"exemption_reason_code": text_of(sub, "cac:TaxCategory/cbc:TaxExemptionReasonCode"),
			})

	lmt = root.find("cac:LegalMonetaryTotal", UBL_NS)
	return {
		"schema_version": "1.0",
		"document": {
			"document_type": doc_type,
			"invoice_kind": kind,
			"invoice_number": text_of(root, "cbc:ID"),
			"invoice_date": text_of(root, "cbc:IssueDate"),
			"due_date": text_of(root, "cbc:DueDate") or text_of(root, "cac:PaymentMeans/cbc:PaymentDueDate"),
			"tax_point_date": text_of(root, "cbc:TaxPointDate"),
			"currency": currency,
			"tax_currency": text_of(root, "cbc:TaxCurrencyCode"),
			"direction": "INBOUND",
			"transaction_type_flags": text_of(root, "cbc:ProfileExecutionID"),
			"notes": text_of(root, "cbc:Note"),
			"buyer_reference": text_of(root, "cbc:BuyerReference"),
			"customization_id": text_of(root, "cbc:CustomizationID"),
		},
		"supplier": _parse_party(root.find("cac:AccountingSupplierParty/cac:Party", UBL_NS)),
		"customer": _parse_party(root.find("cac:AccountingCustomerParty/cac:Party", UBL_NS)),
		"lines": lines,
		"tax_breakdown": breakdown,
		"totals": {
			"subtotal": text_of(lmt, "cbc:LineExtensionAmount"),
			"tax_exclusive": text_of(lmt, "cbc:TaxExclusiveAmount"),
			"tax_total": tax_total,
			"grand_total": text_of(lmt, "cbc:TaxInclusiveAmount"),
			"allowance_total": text_of(lmt, "cbc:AllowanceTotalAmount"),
			"charge_total": text_of(lmt, "cbc:ChargeTotalAmount"),
			"prepaid_amount": text_of(lmt, "cbc:PrepaidAmount"),
			"rounding_amount": text_of(lmt, "cbc:PayableRoundingAmount"),
			"payable_amount": text_of(lmt, "cbc:PayableAmount"),
		},
		"payment": {
			"means_code": text_of(root, "cac:PaymentMeans/cbc:PaymentMeansCode"),
			"terms": text_of(root, "cac:PaymentTerms/cbc:Note"),
			"iban": text_of(root, "cac:PaymentMeans/cac:PayeeFinancialAccount/cbc:ID"),
		},
		"references": {
			"order_reference": text_of(root, "cac:OrderReference/cbc:ID"),
			"contract_reference": text_of(root, "cac:ContractDocumentReference/cbc:ID"),
			"original_invoice_number": text_of(root, "cac:BillingReference/cac:InvoiceDocumentReference/cbc:ID"),
			"original_invoice_date": text_of(root, "cac:BillingReference/cac:InvoiceDocumentReference/cbc:IssueDate"),
		},
	}
