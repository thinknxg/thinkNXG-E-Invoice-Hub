"""Canonical invoice <-> UBL 2.1 Invoice / CreditNote in the Peppol PINT AE 1.0.5 layout.

Element bindings follow the official PINT AE 1.0.5 example documents and rules
(BTAE-* are UAE extension terms, IBT-* PINT terms).
"""

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
from thinknxg_einvoice_hub.compliance.uae import codes, tax_rules
from thinknxg_einvoice_hub.exceptions import PermanentError
from thinknxg_einvoice_hub.utils import money, to_decimal

ZERO = Decimal("0")

# (document_type, invoice_kind) -> UNCL 1001 code used by PINT AE 1.0.5
# billing: invoice 380 / 480 (out of scope of VAT), credit note 381 / 81 (related to goods or services);
# self-billing: invoice 389 / 480, credit note 261 / 81 (official code lists UNCL1001-inv / -cn).
TYPE_CODES = {
	("INVOICE", "TAX"): "380",
	("INVOICE", "COMMERCIAL"): "480",
	("CREDIT_NOTE", "TAX"): "381",
	("CREDIT_NOTE", "COMMERCIAL"): "81",
	("SELF_BILLING_INVOICE", "TAX"): "389",
	("SELF_BILLING_INVOICE", "COMMERCIAL"): "480",
	("SELF_BILLING_CREDIT_NOTE", "TAX"): "261",
	("SELF_BILLING_CREDIT_NOTE", "COMMERCIAL"): "81",
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
AED = "AED"
GTIN_SCHEME = "0160"


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
			# BTAE-15/16 type and BTAE-11/12 authority (passport: BTAE-18/19 issuing country)
			cbc("CompanyID", party.get("legal_registration_id"), schemeAgencyID=party.get("legal_registration_type"),
				schemeAgencyName=party.get("legal_registration_authority")),
		),
		cac("Contact",
			cbc("Name", contact.get("name")),
			cbc("Telephone", contact.get("phone")),
			cbc("ElectronicMail", contact.get("email")),
		),
	)


def _percent(category, rate, context):
	"""Where PINT AE wants a percent: never for O; for E only on document level allowances / charges
	(aligned-ibrp-e-05/-06/-07, ibr-121-ae); always for S, Z, AE and N."""
	if category == "OUT_OF_SCOPE":
		return None
	if category == "EXEMPT" and context != "allowance":
		return None
	return _num(rate)


def _tax_category(tag, category, rate, context, reason=None, reason_code=None):
	if category == "STANDARD":
		reason = reason_code = None  # aligned-ibrp-s-10: no exemption reason on standard rate
	return cac(tag,
		cbc("ID", tax_rules.category_code(category)),
		cbc("Percent", _percent(category, rate, context)),
		cbc("TaxExemptionReasonCode", reason_code),
		cbc("TaxExemptionReason", reason),
		cac("TaxScheme", cbc("ID", "VAT")),
	)


def _line(line, currency, rate, credit):
	category = line.get("tax_category")
	discount = to_decimal(line.get("discount_amount"), ZERO)
	name = line.get("item_name") or line.get("description")
	description = line.get("description") or name  # IBT-154 is mandatory in PINT AE (ibr-125-ae)
	base = to_decimal(line.get("price_base_quantity"), Decimal("1")) or Decimal("1")
	price = to_decimal(line.get("unit_price"), ZERO)
	net = money(line.get("net_amount")) or ZERO
	tax = money(line.get("tax_amount")) or ZERO
	tax_aed = money(tax * rate)
	reasons = category in ("EXEMPT", "OUT_OF_SCOPE")
	return cac("CreditNoteLine" if credit else "InvoiceLine",
		cbc("ID", line.get("line_id")),
		cbc("Note", line.get("note")),
		cbc("CreditedQuantity" if credit else "InvoicedQuantity", _num(line.get("quantity")), unitCode=line.get("unit_code")),
		cbc("LineExtensionAmount", _amt(net), currencyID=currency),
		cac("AllowanceCharge",
			cbc("ChargeIndicator", "false"),
			cbc("AllowanceChargeReason", "Discount"),
			cbc("Amount", _amt(discount), currencyID=currency),
		) if discount > 0 else None,
		cac("Item",
			cbc("Description", description),
			cbc("Name", name),
			cac("SellersItemIdentification", cbc("ID", line.get("item_code"))),
			cac("StandardItemIdentification", cbc("ID", line.get("standard_item_id"),
				schemeID=line.get("standard_item_scheme") or GTIN_SCHEME)),
			# BTAE-17 service accounting code (mandatory for services up to PINT AE 1.0.4, optional in 1.0.5)
			cac("AdditionalItemIdentification", cbc("ID", line.get("service_accounting_code"), schemeID="SAC")),
			cac("CommodityClassification",
				cbc("NatureCode", line.get("rcm_goods_type")),          # BTAE-09
				cbc("CommodityCode", line.get("item_type")),            # BTAE-13
				cbc("ItemClassificationCode", line.get("commodity_code"), listID="HS"),
			),
			_tax_category("ClassifiedTaxCategory", category, line.get("tax_rate"), "line",
				line.get("exemption_reason") if reasons else None,
				line.get("exemption_reason_code") if reasons else None),
		),
		cac("Price",
			cbc("PriceAmount", _num(price), currencyID=currency),
			cbc("BaseQuantity", _num(base), unitCode=line.get("unit_code")),
			cac("AllowanceCharge",                                     # IBT-148 gross price (ibr-126-ae)
				cbc("ChargeIndicator", "false"),
				cbc("Amount", "0", currencyID=currency),
				cbc("BaseAmount", _num(price), currencyID=currency),
			),
		),
		cac("ItemPriceExtension",
			cbc("Amount", _amt((net + tax) * rate), currencyID=AED),    # BTAE-10, line amount incl. VAT in AED
			# BTAE-08 line VAT in AED; not allowed for exempt lines (ibr-163-ae)
			None if category == "EXEMPT" else cac("TaxTotal", cbc("TaxAmount", _amt(tax_aed), currencyID=AED)),
		),
	)


def build(inv, profile):
	"""Render a normalised canonical invoice as PINT AE 1.0.5 UBL XML."""
	doc = inv.get("document") or {}
	totals = inv.get("totals") or {}
	refs = inv.get("references") or {}
	payment = inv.get("payment") or {}
	delivery = inv.get("delivery") or {}
	period = doc.get("invoice_period") or {}
	doc_type = doc.get("document_type")
	kind = doc.get("invoice_kind") or "TAX"
	type_code = TYPE_CODES.get((doc_type, kind))
	if not type_code:
		raise PermanentError(f"Document type {doc_type}/{kind} is not supported by PINT AE")
	credit = doc_type in CREDIT_TYPES
	selfbilling = doc_type in SELF_BILLING
	currency = doc.get("currency")
	tax_currency = doc.get("tax_currency") or profile.get("default_currency") or currency
	foreign = bool(currency) and currency != AED
	rate = (to_decimal(doc.get("exchange_rate"), Decimal("1")) or Decimal("1")) if foreign else Decimal("1")
	scheme = profile.get("endpoint_scheme")
	flags = doc.get("transaction_type_flags")
	reason_code = refs.get("credit_reason_code")
	invoice_date = doc.get("invoice_date") or ""
	tax_point = doc.get("tax_point_date")
	if credit or not tax_point or str(tax_point) >= str(invoice_date):
		tax_point = None  # ibr-124-ae / ibr-141-ae: only when earlier than the issue date, never on credit notes

	children = [
		cbc("CustomizationID", profile["selfbilling_customization_id" if selfbilling else "customization_id"]),
		cbc("ProfileID", profile["selfbilling_profile_id" if selfbilling else "profile_id"]),
		cbc("ProfileExecutionID", flags),
		cbc("ID", doc.get("invoice_number")),
		cbc("UUID", doc.get("uuid")),
		cbc("IssueDate", invoice_date),
		cbc("IssueTime", doc.get("issue_time")),
	]
	if credit:
		children += [cbc("CreditNoteTypeCode", type_code), cbc("Note", doc.get("notes"))]
	else:
		children += [cbc("DueDate", doc.get("due_date")), cbc("InvoiceTypeCode", type_code),
			cbc("Note", doc.get("notes")), cbc("TaxPointDate", tax_point)]
	children += [
		cbc("DocumentCurrencyCode", currency),
		cbc("TaxCurrencyCode", tax_currency if tax_currency != currency else None),
		cbc("BuyerReference", doc.get("buyer_reference")),
		cac("InvoicePeriod",
			cbc("StartDate", period.get("start_date")),
			cbc("EndDate", period.get("end_date")),
			cbc("DescriptionCode", period.get("frequency_code")),   # IBT-008 frequency of billing
		),
	]
	if credit:
		children.append(cac("DiscrepancyResponse",
			cbc("ResponseCode", reason_code),                       # BTAE-03
			cbc("Description", refs.get("credit_reason")),
		))
	children.append(cac("OrderReference", cbc("ID", refs.get("order_reference"))))
	if reason_code != codes.VOLUME_DISCOUNT:  # ibr-055-ae: no preceding invoice for a volume discount
		children.append(cac("BillingReference", cac("InvoiceDocumentReference",
			cbc("ID", refs.get("original_invoice_number")),
			cbc("IssueDate", refs.get("original_invoice_date")),
		)))
	children.append(cac("ContractDocumentReference", cbc("ID", refs.get("contract_reference"))))
	if foreign:
		children.append(cac("AdditionalDocumentReference",          # BTAE-20, ibr-175-ae
			cbc("ID", AED),
			cbc("DocumentTypeCode", codes.AED_TOTAL_REFERENCE),
			cbc("DocumentDescription", _amt(to_decimal(totals.get("grand_total"), ZERO) * rate)),
		))
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
	# ibr-191-ae: payment means is mandatory on invoices; "1" (instrument not defined) when the ERP sent none
	if not credit or payment.get("means_code") or payment.get("iban") or doc.get("due_date"):
		children.append(cac("PaymentMeans",
			cbc("PaymentMeansCode", payment.get("means_code") or "1"),
			cbc("PaymentDueDate", doc.get("due_date")) if credit else None,
			cac("PayeeFinancialAccount", cbc("ID", payment.get("iban")), cbc("Name", payment.get("account_name"))),
		))
	children.append(cac("PaymentTerms", cbc("Note", payment.get("terms"))))

	allowances = [cac("AllowanceCharge",
		cbc("ChargeIndicator", "true" if ac.get("is_charge") else "false"),
		cbc("AllowanceChargeReason", ac.get("reason")),
		cbc("Amount", _amt(ac.get("amount")), currencyID=currency),
		_tax_category("TaxCategory", ac.get("tax_category"), ac.get("tax_rate"), "allowance",
			ac.get("exemption_reason"), ac.get("exemption_reason_code")),
	) for ac in inv.get("allowances_charges") or []]
	exchange = cac("TaxExchangeRate",                                # BTAE-04, ibr-153-ae / ibr-159-ae
		cbc("SourceCurrencyCode", currency),
		cbc("TargetCurrencyCode", AED),
		cbc("CalculationRate", _num(rate)),
	) if foreign else None
	# UBL 2.1 element order: Invoice has AllowanceCharge before TaxExchangeRate, CreditNote after it
	children += ([exchange] + allowances) if credit else (allowances + [exchange])

	tax_total = cac("TaxTotal",
		cbc("TaxAmount", _amt(totals.get("tax_total")), currencyID=currency),
		cbc("TaxIncludedIndicator", "false"),
	)
	for row in inv.get("tax_breakdown") or []:
		tax_total.add(cac("TaxSubtotal",
			cbc("TaxableAmount", _amt(row.get("taxable_amount")), currencyID=currency),
			cbc("TaxAmount", _amt(row.get("tax_amount")), currencyID=currency),
			_tax_category("TaxCategory", row.get("tax_category"), row.get("tax_rate"), "subtotal",
				row.get("exemption_reason"), row.get("exemption_reason_code")),
		))
	children.append(tax_total)
	if foreign:
		converted = to_decimal(totals.get("tax_total"), ZERO) * rate
		children.append(cac("TaxTotal", cbc("TaxAmount", _amt(converted), currencyID=AED)))

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
	children += [_line(line, currency, rate, credit) for line in inv.get("lines") or []]

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
		"legal_registration_authority": attr_of(node, "cac:PartyLegalEntity/cbc:CompanyID", "schemeAgencyName"),
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
	if "selfbilling" in (text_of(root, "cbc:CustomizationID") or ""):
		doc_type = "SELF_BILLING_CREDIT_NOTE" if credit else "SELF_BILLING_INVOICE"
	elif credit:
		doc_type = "CREDIT_NOTE"
	currency = text_of(root, "cbc:DocumentCurrencyCode")

	lines = []
	for node in root.findall("cac:CreditNoteLine" if credit else "cac:InvoiceLine", UBL_NS):
		qty_path = "cbc:CreditedQuantity" if credit else "cbc:InvoicedQuantity"
		code = text_of(node, "cac:Item/cac:ClassifiedTaxCategory/cbc:ID")
		category = tax_rules.category_from_code(code) or code
		# BTAE-08 is in AED, so it is the line VAT only for AED documents; RC / margin lines carry none
		line_tax = text_of(node, "cac:ItemPriceExtension/cac:TaxTotal/cbc:TaxAmount") if currency == AED else None
		if category in tax_rules.NO_TAX_CATEGORIES:
			line_tax = "0"
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
			"tax_category": category,
			"tax_rate": text_of(node, "cac:Item/cac:ClassifiedTaxCategory/cbc:Percent") or 0,
			"tax_amount": line_tax,
			"exemption_reason_code": text_of(node, "cac:Item/cac:ClassifiedTaxCategory/cbc:TaxExemptionReasonCode"),
			"exemption_reason": text_of(node, "cac:Item/cac:ClassifiedTaxCategory/cbc:TaxExemptionReason"),
			"commodity_code": text_of(node, "cac:Item/cac:CommodityClassification/cbc:ItemClassificationCode"),
			"item_type": text_of(node, "cac:Item/cac:CommodityClassification/cbc:CommodityCode"),
			"rcm_goods_type": text_of(node, "cac:Item/cac:CommodityClassification/cbc:NatureCode"),
			"standard_item_id": text_of(node, "cac:Item/cac:StandardItemIdentification/cbc:ID"),
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
			"uuid": text_of(root, "cbc:UUID"),
			"invoice_date": text_of(root, "cbc:IssueDate"),
			"issue_time": text_of(root, "cbc:IssueTime"),
			"due_date": text_of(root, "cbc:DueDate") or text_of(root, "cac:PaymentMeans/cbc:PaymentDueDate"),
			"tax_point_date": text_of(root, "cbc:TaxPointDate"),
			"currency": currency,
			"tax_currency": text_of(root, "cbc:TaxCurrencyCode"),
			"direction": "INBOUND",
			"transaction_type_flags": text_of(root, "cbc:ProfileExecutionID"),
			"notes": text_of(root, "cbc:Note"),
			"buyer_reference": text_of(root, "cbc:BuyerReference"),
			"customization_id": text_of(root, "cbc:CustomizationID"),
			"invoice_period": {k: v for k, v in (
				("start_date", text_of(root, "cac:InvoicePeriod/cbc:StartDate")),
				("end_date", text_of(root, "cac:InvoicePeriod/cbc:EndDate")),
				("frequency_code", text_of(root, "cac:InvoicePeriod/cbc:DescriptionCode")),
			) if v} or None,
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
			"credit_reason_code": text_of(root, "cac:DiscrepancyResponse/cbc:ResponseCode"),
			"credit_reason": text_of(root, "cac:DiscrepancyResponse/cbc:Description"),
		},
	}
