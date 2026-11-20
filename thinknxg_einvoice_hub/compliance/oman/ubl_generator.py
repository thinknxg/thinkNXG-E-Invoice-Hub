"""Canonical invoice <-> PINT OM UBL 2.1 Invoice / CreditNote.

Element layout follows the official PINT OM 1.0.1 examples and syntax binding
(docs.peppol.eu/poac/om/pint-om). Oman-specific terms and where they are written:

==========  ==================================  ======================================================
Term        Canonical field                      UBL
==========  ==================================  ======================================================
BTOM-001    document.transaction_type_flags     cbc:InvoiceTypeCode/@name (CreditNoteTypeCode/@name)
BTOM-002    document.uuid (computed)            cbc:UUID
IBT-168     document.issue_time                 cbc:IssueTime
BTOM-003    document.exchange_rate              cac:TaxExchangeRate/cbc:CalculationRate
BTOM-004    supplier.uuid (Seller UUID)         cac:AccountingSupplierParty/cbc:AdditionalAccountID
BTOM-015/8  party.identifier(_scheme)           cac:PartyIdentification/cbc:ID/@schemeName
CL-13-OM    address.subdivision                 cbc:CountrySubentityCode
IBT-162/3   address.address_line                cac:AddressLine/cbc:Line
BTOM-031/2  references.original_invoice_uuid,   cac:BillingReference/cac:InvoiceDocumentReference
            references.credit_reason_code         (cbc:UUID, cbc:DocumentStatusCode)
BTOM-027/14 references.prepayment_number/uuid   cac:AdditionalDocumentReference[DocumentTypeCode=PDR]
BTOM-020    extensions.om.pm_total              cac:AdditionalDocumentReference[DocumentTypeCode=PM_TOTAL]
BTOM-033    line.industry_code (ISIC, 6)        cac:Item/cac:AdditionalItemIdentification/cbc:ID[@schemeName=CC]
BTOM-019/34 line.item_type, line.service_type   cac:Item/cac:ItemSpecificationDocumentReference
IBT-158     line.commodity_code (HS, 12)        cac:Item/cac:CommodityClassification/cbc:ItemClassificationCode[@listID=HS]
BTOM-025    line.profit_margin_code             cac:Item/cac:AdditionalItemProperty/cbc:NameCode
BTOM-016/7  line.tax_amount                     cac:ItemPriceExtension (cac:TaxTotal/cbc:TaxAmount, cbc:Amount)
==========  ==================================  ======================================================

Decimals follow the official rules and examples (P1-P4 "baisa gap" samples):
line amounts and line VAT use the currency's minor unit (3 for OMR, IBR-DEC-03-OM);
document-level totals - VAT breakdown, TaxTotal and LegalMonetaryTotal - carry at
most 2 decimals (ibr-091, ibr-123..125) and are each rounded once from the line
sums (ibr-co-10/14/15, ALIGNED-IBRP-S-08/S-09-OM). ``document_amount_decimals`` in
engine settings changes the 2 if a later ruleset does.

The Invoice UUID is computed from the values exactly as written (OM SRA 10.2.3),
so it always matches what the accredited provider recomputes.
"""

from decimal import ROUND_HALF_UP, Decimal

from thinknxg_einvoice_hub.compliance.oman import constants as C
from thinknxg_einvoice_hub.compliance.oman import identifiers, transaction_types
from thinknxg_einvoice_hub.compliance.shared.xml import (
	CREDIT_NOTE_NS,
	INVOICE_NS,
	El,
	UBL_NS,
	attr_of,
	cac,
	cbc,
	parse_xml,
	render_document,
	text_of,
)
from thinknxg_einvoice_hub.exceptions import PermanentError
from thinknxg_einvoice_hub.utils import currency_places, to_decimal

ZERO = Decimal("0")


def q(value, places):
	return to_decimal(value, ZERO).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def fmt(value, places):
	return f"{q(value, places):.{places}f}"


def num(value):
	"""Plain number without trailing zeros (quantities, prices, percentages)."""
	text = format(to_decimal(value, ZERO).normalize(), "f")
	return text if text not in ("-0", "") else "0"


def _address(tag, addr):
	addr = addr or {}
	return cac(tag,
		cbc("StreetName", addr.get("street")),
		cbc("AdditionalStreetName", addr.get("additional_street")),
		cbc("CityName", addr.get("city")),
		cbc("PostalZone", addr.get("postal_code")),
		cbc("CountrySubentity", addr.get("subdivision_name")),
		cbc("CountrySubentityCode", addr.get("subdivision")),
		cac("AddressLine", cbc("Line", addr.get("address_line"))),
		cac("Country", cbc("IdentificationCode", addr.get("country"))),
	)


def _identifier(party):
	value, scheme = party.get("identifier"), party.get("identifier_scheme")
	if not value and party.get("legal_registration_type") in C.IDENTIFIER_SCHEMES:
		value, scheme = party.get("legal_registration_id"), party.get("legal_registration_type")
	return value, scheme


def _party(party, default_scheme):
	party = party or {}
	contact = party.get("contact") or {}
	ident, scheme = _identifier(party)
	tax_scheme = None
	if party.get("tax_id"):
		tax_scheme = cac("PartyTaxScheme", cbc("CompanyID", party["tax_id"]), cac("TaxScheme", cbc("ID", "VAT")))
	legal_id = party.get("legal_registration_id") if party.get("legal_registration_id") != ident else None
	return cac("Party",
		cbc("EndpointID", party.get("tin"), schemeID=party.get("endpoint_scheme") or default_scheme),
		cac("PartyIdentification", cbc("ID", ident, schemeName=scheme)),
		cac("PartyName", cbc("Name", party.get("trading_name"))),
		_address("PostalAddress", party.get("address")),
		tax_scheme,
		cac("PartyLegalEntity", cbc("RegistrationName", party.get("legal_name")), cbc("CompanyID", legal_id)),
		cac("Contact",
			cbc("Name", contact.get("name")),
			cbc("Telephone", contact.get("phone")),
			cbc("ElectronicMail", contact.get("email")),
		),
	)


class Builder:
	def __init__(self, profile, rules):
		self.profile = profile
		self.rules = rules

	# ------------------------------------------------------------ pieces
	def _tax_category(self, tag, category, rate, reason=None, reason_code=None):
		exempt_like = category in ("EXEMPT", "ZERO_RATED")
		return cac(tag,
			cbc("ID", self.rules.code(category)),
			cbc("Percent", num(rate) if self.rules.has_rate(category) else None),
			cbc("TaxExemptionReasonCode", reason_code if exempt_like else None),
			cbc("TaxExemptionReason", reason if exempt_like else None),
			cac("TaxScheme", cbc("ID", "VAT")),
		)

	def _line(self, line, currency, credit, dp):
		discount = to_decimal(line.get("discount_amount"), ZERO)
		name = line.get("item_name") or line.get("description")
		description = line.get("description") if line.get("description") != name else None
		base = to_decimal(line.get("price_base_quantity"), Decimal("1"))
		net = q(line.get("net_amount"), dp)
		vat = q(line.get("tax_amount"), dp)
		item_type = line.get("item_type")
		service_type = line.get("service_type") or (C.DEFAULT_SERVICE_TYPE if item_type else None)
		hs = line.get("commodity_code") if (line.get("commodity_list") or "HS") == "HS" else None
		pm_code = line.get("profit_margin_code")
		return cac("CreditNoteLine" if credit else "InvoiceLine",
			cbc("ID", line.get("line_id")),
			cbc("Note", line.get("note")),
			cbc("CreditedQuantity" if credit else "InvoicedQuantity", num(line.get("quantity")), unitCode=line.get("unit_code")),
			cbc("LineExtensionAmount", fmt(net, dp), currencyID=currency),
			cac("InvoicePeriod", cbc("StartDate", line.get("period_start")), cbc("EndDate", line.get("period_end"))),
			cac("AllowanceCharge",
				cbc("ChargeIndicator", "false"),
				cbc("AllowanceChargeReasonCode", "95"),
				cbc("AllowanceChargeReason", "Discount"),
				cbc("Amount", fmt(discount, dp), currencyID=currency),
			) if discount > 0 else None,
			cac("Item",
				cbc("Description", description),
				cbc("Name", name),
				cac("SellersItemIdentification", cbc("ID", line.get("item_code"))),
				cac("AdditionalItemIdentification", cbc("ID", line.get("industry_code"), schemeName="CC")),
				cac("ItemSpecificationDocumentReference",
					cbc("ID", service_type, schemeName="MP"),
					cbc("DocumentTypeCode", item_type),
				) if item_type else None,
				cac("OriginCountry", cbc("IdentificationCode", line.get("origin_country"))),
				cac("CommodityClassification", cbc("ItemClassificationCode", hs, listID="HS")),
				self._tax_category("ClassifiedTaxCategory", line.get("tax_category"), line.get("tax_rate"),
					line.get("exemption_reason"), line.get("exemption_reason_code")),
				cac("AdditionalItemProperty",
					cbc("Name", "Profit margin reason"),
					cbc("NameCode", pm_code),
					cbc("Value", C.PROFIT_MARGIN_CODES.get(pm_code, pm_code)),
				) if pm_code else None,
			),
			cac("Price",
				cbc("PriceAmount", num(line.get("unit_price")), currencyID=currency),
				cbc("BaseQuantity", num(base), unitCode=line.get("unit_code")) if base != 1 else None,
			),
			cac("ItemPriceExtension",
				cbc("Amount", fmt(net + vat, dp), currencyID=currency),
				cac("TaxTotal", cbc("TaxAmount", fmt(vat, dp), currencyID=currency)),
			),
		)

	def _ac(self, ac, currency, dp):
		return cac("AllowanceCharge",
			cbc("ChargeIndicator", "true" if ac.get("is_charge") else "false"),
			cbc("AllowanceChargeReasonCode", ac.get("reason_code") or ("ZZZ" if ac.get("is_charge") else "95")),
			cbc("AllowanceChargeReason", ac.get("reason")),
			cbc("Amount", fmt(ac.get("amount"), dp), currencyID=currency),
			self._tax_category("TaxCategory", ac.get("tax_category"), ac.get("tax_rate"),
				ac.get("exemption_reason"), ac.get("exemption_reason_code")),
		)

	@staticmethod
	def _exact_rows(rows, lines, acs, line_dp):
		"""Breakdown amounts recomputed as ruleset 1.0.1 does before rounding once to 2 decimals
		(ALIGNED-IBRP-S-08/S-09-OM): sum of line net / line VAT as written (3 decimals) plus charges minus
		allowances, with allowance/charge VAT taken unrounded."""
		out = []
		for row in rows:
			cat, rate = row.get("tax_category"), to_decimal(row.get("tax_rate"), ZERO)
			match = [l for l in lines if l.get("tax_category") == cat and to_decimal(l.get("tax_rate"), ZERO) == rate]
			if not match:
				out.append(row)
				continue
			taxable = sum((q(l.get("net_amount"), line_dp) for l in match), ZERO)
			vat = sum((q(l.get("tax_amount"), line_dp) for l in match), ZERO)
			for ac in acs:
				if ac.get("tax_category") == cat and to_decimal(ac.get("tax_rate"), ZERO) == rate:
					amount = q(ac.get("amount"), line_dp) * (1 if ac.get("is_charge") else -1)
					taxable += amount
					vat += amount * rate / 100 if cat == "STANDARD" else ZERO
			out.append(dict(row, taxable_amount=taxable, tax_amount=vat))
		return out

	def _tax_total(self, rows, currency, places, factor=None, subtotals=True):
		"""One cac:TaxTotal. ``factor`` restates it in the tax currency (OMR) for foreign invoices (IBR-066-OM)."""
		subs, total = [], ZERO
		for row in rows:
			taxable = to_decimal(row.get("taxable_amount"), ZERO)
			vat = to_decimal(row.get("tax_amount"), ZERO)
			if factor is not None:
				taxable, vat = taxable * factor, vat * factor
			taxable, vat = q(taxable, places), q(vat, places)
			total += vat
			subs.append(cac("TaxSubtotal",
				cbc("TaxableAmount", fmt(taxable, places), currencyID=currency),
				cbc("TaxAmount", fmt(vat, places), currencyID=currency),
				self._tax_category("TaxCategory", row.get("tax_category"), row.get("tax_rate"),
					row.get("exemption_reason"), row.get("exemption_reason_code")),
			))
		return cac("TaxTotal", cbc("TaxAmount", fmt(total, places), currencyID=currency), *(subs if subtotals else [])), total

	# ------------------------------------------------------------ document
	def build(self, inv):
		"""Return ``(xml, meta)``; ``meta`` has the computed ``uuid`` and the amounts as written."""
		profile = self.profile
		doc = inv.get("document") or {}
		totals = inv.get("totals") or {}
		refs = inv.get("references") or {}
		payment = inv.get("payment") or {}
		delivery = inv.get("delivery") or {}
		om = (inv.get("extensions") or {}).get("om") or {}
		doc_type = doc.get("document_type")
		type_code = C.TYPE_CODES.get(doc_type)
		if not type_code or (doc.get("invoice_kind") or "TAX") != "TAX":
			raise PermanentError(f"Document type {doc_type}/{doc.get('invoice_kind')} is not supported by PINT OM")
		credit = doc_type in C.CREDIT_TYPES
		selfbilling = doc_type in C.SELF_BILLING
		currency = doc.get("currency")
		dp = currency_places(currency)
		ddp = int(profile.get("document_amount_decimals") or 2)
		tax_currency = profile.get("default_currency") or C.TAX_CURRENCY
		foreign = currency != tax_currency
		scheme = profile.get("endpoint_scheme") or C.ENDPOINT_SCHEME
		flags = doc.get("transaction_type_flags")
		lines = inv.get("lines") or []
		supplier = inv.get("supplier") or {}
		customer = inv.get("customer") or {}

		# ---- amounts first: the Invoice UUID is computed from them as written
		rows = self._exact_rows(inv.get("tax_breakdown") or [], lines, inv.get("allowances_charges") or [], dp)
		# Foreign-currency invoice with standard-rated supplies: ruleset 1.0.1 requires the S breakdown in OMR
		# (IBR-066-OM) and allows only one S breakdown per document (ALIGNED-IBRP-S-01-OM), so the breakdown goes
		# in the OMR TaxTotal and the document-currency TaxTotal carries the total only. Otherwise the breakdown
		# stays in the document currency, as in the official Exports-2 example.
		breakdown_in_omr = foreign and any(r.get("tax_category") == "STANDARD" for r in rows)
		tax_total_el, vat_total = self._tax_total(rows, currency, ddp, subtotals=not breakdown_in_omr)
		rate = to_decimal(doc.get("exchange_rate"), Decimal("1")).quantize(Decimal("0.0000001"), rounding=ROUND_HALF_UP)
		line_total = q(sum((q(l.get("net_amount"), dp) for l in lines), ZERO), ddp)
		allowance = q(sum((q(a.get("amount"), dp) for a in inv.get("allowances_charges") or [] if not a.get("is_charge")), ZERO), ddp)
		charge = q(sum((q(a.get("amount"), dp) for a in inv.get("allowances_charges") or [] if a.get("is_charge")), ZERO), ddp)
		tax_exclusive = line_total - allowance + charge
		tax_inclusive = tax_exclusive + vat_total
		prepaid = q(totals.get("prepaid_amount"), ddp)
		rounding = q(totals.get("rounding_amount"), dp)
		payable = tax_inclusive - prepaid + rounding
		written = {"tax_total": fmt(vat_total, ddp), "tax_inclusive": fmt(tax_inclusive, ddp)}
		profit_margin = transaction_types.has(flags, "PROFIT_MARGIN") or transaction_types.has(flags, "PROFIT_MARGIN_SELF_INVOICE")
		pm_total = om.get("pm_total")
		pm_text = fmt(pm_total, 3) if pm_total not in (None, "") else None

		uuid = doc.get("uuid") or identifiers.invoice_uuid(
			scheme, supplier.get("tin"), type_code, doc.get("invoice_number"), doc.get("invoice_date"),
			written["tax_total"], written["tax_inclusive"], pm_text if profit_margin else None,
			namespace=profile.get("uuid_namespace"))

		children = [
			cbc("CustomizationID", profile["selfbilling_customization_id" if selfbilling else "customization_id"]),
			cbc("ProfileID", profile["selfbilling_profile_id" if selfbilling else "profile_id"]),
			cbc("ID", doc.get("invoice_number")),
			cbc("UUID", uuid),
			cbc("IssueDate", doc.get("invoice_date")),
			cbc("IssueTime", doc.get("issue_time")),
		]
		if credit:
			children += [cbc("TaxPointDate", doc.get("tax_point_date")),
				El("cbc:CreditNoteTypeCode", type_code, {"name": flags}), cbc("Note", doc.get("notes"))]
		else:
			children += [cbc("DueDate", doc.get("due_date")), El("cbc:InvoiceTypeCode", type_code, {"name": flags}),
				cbc("Note", doc.get("notes")), cbc("TaxPointDate", doc.get("tax_point_date"))]
		children += [
			cbc("DocumentCurrencyCode", currency),
			cbc("TaxCurrencyCode", tax_currency if foreign else None),
			cbc("BuyerReference", doc.get("buyer_reference")),
			cac("InvoicePeriod", cbc("StartDate", doc.get("period_start")), cbc("EndDate", doc.get("period_end"))),
			cac("OrderReference", cbc("ID", refs.get("order_reference"))),
			cac("BillingReference", cac("InvoiceDocumentReference",
				cbc("ID", refs.get("original_invoice_number")),
				cbc("UUID", refs.get("original_invoice_uuid")),
				cbc("IssueDate", refs.get("original_invoice_date")),
				cbc("DocumentStatusCode", refs.get("credit_reason_code")),
				cbc("DocumentDescription", refs.get("credit_reason")),
			)),
			cac("ContractDocumentReference", cbc("ID", refs.get("contract_reference"))),
		]
		if refs.get("prepayment_number"):
			children.append(cac("AdditionalDocumentReference", cbc("ID", refs.get("prepayment_number")),
				cbc("UUID", refs.get("prepayment_uuid")), cbc("DocumentTypeCode", "PDR")))
		if pm_text:
			children.append(cac("AdditionalDocumentReference", cbc("ID", "OMR"),
				cbc("DocumentTypeCode", "PM_TOTAL"), cbc("DocumentDescription", pm_text)))
		for att in inv.get("attachments") or []:
			children.append(cac("AdditionalDocumentReference",
				cbc("ID", att.get("id") or att.get("filename")),
				cbc("UUID", att.get("uuid")),
				cbc("DocumentDescription", att.get("description")),
				cac("Attachment", cbc("EmbeddedDocumentBinaryObject", att.get("content_base64"),
					mimeCode=att.get("mime_type"), filename=att.get("filename"))),
			))
		children += [
			cac("AccountingSupplierParty", cbc("AdditionalAccountID", supplier.get("uuid")), _party(supplier, scheme)),
			cac("AccountingCustomerParty", _party(customer, scheme)),
			cac("Delivery",
				cbc("ActualDeliveryDate", delivery.get("date")),
				cac("DeliveryLocation", _address("Address", delivery.get("address"))),
				cac("DeliveryTerms", cbc("ID", delivery.get("incoterms"), schemeID="incoterms")),
				cac("Shipment", cbc("ID", delivery.get("customs_declaration")),
					cac("Delivery", cbc("ActualDeliveryDate", delivery.get("import_date")))),
			),
		]
		if payment.get("means_code") or payment.get("iban"):
			children.append(cac("PaymentMeans",
				cbc("PaymentMeansCode", payment.get("means_code") or "30"),
				cbc("PaymentDueDate", doc.get("due_date")) if credit else None,
				cac("PayeeFinancialAccount", cbc("ID", payment.get("iban")), cbc("Name", payment.get("account_name"))),
			))
		children.append(cac("PaymentTerms", cbc("Note", payment.get("terms"))))
		acs = [self._ac(ac, currency, dp) for ac in inv.get("allowances_charges") or []]
		exchange = cac("TaxExchangeRate",
			cbc("SourceCurrencyCode", currency),
			cbc("TargetCurrencyCode", tax_currency),
			cbc("CalculationRate", num(rate)),
		) if foreign else None
		# UBL 2.1 order: Invoice puts AllowanceCharge before TaxExchangeRate, CreditNote after it
		children += ([exchange] + acs) if credit else (acs + [exchange])
		children.append(tax_total_el)
		if foreign:
			children.append(self._tax_total(rows, tax_currency, ddp, factor=rate, subtotals=breakdown_in_omr)[0])

		def opt(name, value, places=ddp):
			return cbc(name, fmt(value, places), currencyID=currency) if value != 0 else None

		children.append(cac("LegalMonetaryTotal",
			cbc("LineExtensionAmount", fmt(line_total, ddp), currencyID=currency),
			cbc("TaxExclusiveAmount", fmt(tax_exclusive, ddp), currencyID=currency),
			cbc("TaxInclusiveAmount", written["tax_inclusive"], currencyID=currency),
			opt("AllowanceTotalAmount", allowance),
			opt("ChargeTotalAmount", charge),
			opt("PrepaidAmount", prepaid),
			opt("PayableRoundingAmount", rounding, dp),
			cbc("PayableAmount", fmt(payable, max(ddp, dp) if rounding else ddp), currencyID=currency),
		))
		children += [self._line(line, currency, credit, dp) for line in lines]
		xml = render_document("CreditNote" if credit else "Invoice", CREDIT_NOTE_NS if credit else INVOICE_NS, children)
		return xml, {"uuid": uuid, **written, "pm_total": pm_text}


# ---------------------------------------------------------------------- inbound
def _parse_address(addr):
	if addr is None:
		return {}
	return {
		"street": text_of(addr, "cbc:StreetName"),
		"additional_street": text_of(addr, "cbc:AdditionalStreetName"),
		"address_line": text_of(addr, "cac:AddressLine/cbc:Line"),
		"city": text_of(addr, "cbc:CityName"),
		"postal_code": text_of(addr, "cbc:PostalZone"),
		"subdivision": text_of(addr, "cbc:CountrySubentityCode"),
		"subdivision_name": text_of(addr, "cbc:CountrySubentity"),
		"country": text_of(addr, "cac:Country/cbc:IdentificationCode"),
	}


def _parse_party(node, outer=None):
	if node is None:
		return {"address": {}}
	return {
		"legal_name": text_of(node, "cac:PartyLegalEntity/cbc:RegistrationName") or text_of(node, "cac:PartyName/cbc:Name"),
		"trading_name": text_of(node, "cac:PartyName/cbc:Name"),
		"tax_id": text_of(node, "cac:PartyTaxScheme/cbc:CompanyID"),
		"tin": text_of(node, "cbc:EndpointID"),
		"endpoint_scheme": attr_of(node, "cbc:EndpointID", "schemeID"),
		"identifier": text_of(node, "cac:PartyIdentification/cbc:ID"),
		"identifier_scheme": attr_of(node, "cac:PartyIdentification/cbc:ID", "schemeName"),
		"legal_registration_id": text_of(node, "cac:PartyLegalEntity/cbc:CompanyID"),
		"uuid": text_of(outer, "cbc:AdditionalAccountID") if outer is not None else None,
		"address": _parse_address(node.find("cac:PostalAddress", UBL_NS)),
		"contact": {
			"name": text_of(node, "cac:Contact/cbc:Name"),
			"phone": text_of(node, "cac:Contact/cbc:Telephone"),
			"email": text_of(node, "cac:Contact/cbc:ElectronicMail"),
		},
	}


def parse(content, rules):
	"""Parse a PINT OM Invoice / CreditNote into an (un-normalised) canonical invoice."""
	root = parse_xml(content)
	local = root.tag.rsplit("}", 1)[-1]
	if local not in ("Invoice", "CreditNote"):
		raise PermanentError(f"Unsupported document root <{local}>; expected Invoice or CreditNote")
	credit = local == "CreditNote"
	type_path = "cbc:CreditNoteTypeCode" if credit else "cbc:InvoiceTypeCode"
	type_code = text_of(root, type_path)
	doc_type = C.CODE_TYPES.get(type_code or "", "CREDIT_NOTE" if credit else "INVOICE")
	currency = text_of(root, "cbc:DocumentCurrencyCode")
	item = "cac:Item/"

	lines = []
	for node in root.findall("cac:CreditNoteLine" if credit else "cac:InvoiceLine", UBL_NS):
		qty_path = "cbc:CreditedQuantity" if credit else "cbc:InvoicedQuantity"
		code = text_of(node, item + "cac:ClassifiedTaxCategory/cbc:ID")
		discount = node.find("cac:AllowanceCharge[cbc:ChargeIndicator='false']", UBL_NS)
		lines.append({
			"line_id": text_of(node, "cbc:ID"),
			"item_code": text_of(node, item + "cac:SellersItemIdentification/cbc:ID"),
			"item_name": text_of(node, item + "cbc:Name"),
			"description": text_of(node, item + "cbc:Description"),
			"quantity": text_of(node, qty_path),
			"unit_code": attr_of(node, qty_path, "unitCode"),
			"unit_price": text_of(node, "cac:Price/cbc:PriceAmount"),
			"price_base_quantity": text_of(node, "cac:Price/cbc:BaseQuantity"),
			"discount_amount": text_of(discount, "cbc:Amount") if discount is not None else None,
			"net_amount": text_of(node, "cbc:LineExtensionAmount"),
			"tax_category": rules.category(code) or code,
			"tax_rate": text_of(node, item + "cac:ClassifiedTaxCategory/cbc:Percent") or 0,
			"tax_amount": text_of(node, "cac:ItemPriceExtension/cac:TaxTotal/cbc:TaxAmount"),
			"exemption_reason_code": text_of(node, item + "cac:ClassifiedTaxCategory/cbc:TaxExemptionReasonCode"),
			"exemption_reason": text_of(node, item + "cac:ClassifiedTaxCategory/cbc:TaxExemptionReason"),
			"item_type": text_of(node, item + "cac:ItemSpecificationDocumentReference/cbc:DocumentTypeCode"),
			"service_type": text_of(node, item + "cac:ItemSpecificationDocumentReference/cbc:ID"),
			"industry_code": text_of(node, item + "cac:AdditionalItemIdentification/cbc:ID"),
			"commodity_code": text_of(node, item + "cac:CommodityClassification/cbc:ItemClassificationCode"),
			"commodity_list": attr_of(node, item + "cac:CommodityClassification/cbc:ItemClassificationCode", "listID"),
			"origin_country": text_of(node, item + "cac:OriginCountry/cbc:IdentificationCode"),
			"profit_margin_code": text_of(node, item + "cac:AdditionalItemProperty/cbc:NameCode"),
			"period_start": text_of(node, "cac:InvoicePeriod/cbc:StartDate"),
			"period_end": text_of(node, "cac:InvoicePeriod/cbc:EndDate"),
		})

	breakdown, tax_total = [], None
	for total in root.findall("cac:TaxTotal", UBL_NS):
		if attr_of(total, "cbc:TaxAmount", "currencyID") not in (None, currency):
			continue  # VAT restated in OMR for a foreign-currency invoice
		tax_total = text_of(total, "cbc:TaxAmount")
		for sub in total.findall("cac:TaxSubtotal", UBL_NS):
			code = text_of(sub, "cac:TaxCategory/cbc:ID")
			breakdown.append({
				"tax_category": rules.category(code) or code,
				"tax_rate": text_of(sub, "cac:TaxCategory/cbc:Percent") or 0,
				"taxable_amount": text_of(sub, "cbc:TaxableAmount"),
				"tax_amount": text_of(sub, "cbc:TaxAmount"),
				"exemption_reason": text_of(sub, "cac:TaxCategory/cbc:TaxExemptionReason"),
				"exemption_reason_code": text_of(sub, "cac:TaxCategory/cbc:TaxExemptionReasonCode"),
			})

	lmt = root.find("cac:LegalMonetaryTotal", UBL_NS)
	ref = "cac:BillingReference/cac:InvoiceDocumentReference/"
	pdr = root.find("cac:AdditionalDocumentReference[cbc:DocumentTypeCode='PDR']", UBL_NS)
	pm = root.find("cac:AdditionalDocumentReference[cbc:DocumentTypeCode='PM_TOTAL']", UBL_NS)
	return {
		"schema_version": "1.0",
		"document": {
			"document_type": doc_type,
			"invoice_kind": "TAX",
			"invoice_number": text_of(root, "cbc:ID"),
			"uuid": text_of(root, "cbc:UUID"),
			"invoice_date": text_of(root, "cbc:IssueDate"),
			"issue_time": text_of(root, "cbc:IssueTime"),
			"due_date": text_of(root, "cbc:DueDate") or text_of(root, "cac:PaymentMeans/cbc:PaymentDueDate"),
			"tax_point_date": text_of(root, "cbc:TaxPointDate"),
			"currency": currency,
			"tax_currency": text_of(root, "cbc:TaxCurrencyCode"),
			"exchange_rate": text_of(root, "cac:TaxExchangeRate/cbc:CalculationRate") or 1,
			"direction": "INBOUND",
			"transaction_type_flags": attr_of(root, type_path, "name"),
			"notes": text_of(root, "cbc:Note"),
			"buyer_reference": text_of(root, "cbc:BuyerReference"),
			"customization_id": text_of(root, "cbc:CustomizationID"),
			"period_start": text_of(root, "cac:InvoicePeriod/cbc:StartDate"),
			"period_end": text_of(root, "cac:InvoicePeriod/cbc:EndDate"),
		},
		"supplier": _parse_party(root.find("cac:AccountingSupplierParty/cac:Party", UBL_NS),
			root.find("cac:AccountingSupplierParty", UBL_NS)),
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
		"delivery": {
			"date": text_of(root, "cac:Delivery/cbc:ActualDeliveryDate"),
			"address": _parse_address(root.find("cac:Delivery/cac:DeliveryLocation/cac:Address", UBL_NS)),
		},
		"references": {
			"order_reference": text_of(root, "cac:OrderReference/cbc:ID"),
			"contract_reference": text_of(root, "cac:ContractDocumentReference/cbc:ID"),
			"original_invoice_number": text_of(root, ref + "cbc:ID"),
			"original_invoice_uuid": text_of(root, ref + "cbc:UUID"),
			"original_invoice_date": text_of(root, ref + "cbc:IssueDate"),
			"credit_reason_code": text_of(root, ref + "cbc:DocumentStatusCode"),
			"credit_reason": text_of(root, ref + "cbc:DocumentDescription"),
			"prepayment_number": text_of(pdr, "cbc:ID") if pdr is not None else None,
			"prepayment_uuid": text_of(pdr, "cbc:UUID") if pdr is not None else None,
		},
		"extensions": {"om": {"pm_total": text_of(pm, "cbc:DocumentDescription")}} if pm is not None else {},
	}
