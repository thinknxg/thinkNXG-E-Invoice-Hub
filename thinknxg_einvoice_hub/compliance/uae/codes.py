"""Code lists of Peppol PINT AE 1.0.5 (billing and self-billing), as published by
OpenPeppol for the UAE Peppol Authority in the official resources (``codelist/*.gc``).

Only the lists the hub checks before submission are copied here. The official
Schematron remains the authority; see ``schematron.py`` for running it.
"""

SPEC_VERSION = "1.0.5"

#: BTAE-03, CreditReason.gc
CREDIT_REASONS = {
	"DL8.61.1.A": "Supply cancelled",
	"DL8.61.1.B": "Tax treatment changed",
	"DL8.61.1.C": "Consideration altered",
	"DL8.61.1.D": "Goods or services returned",
	"DL8.61.1.E": "Tax charged or applied in error",
	"VD": "Volume discount",
}
VOLUME_DISCOUNT = "VD"

#: IBT-121 / IBT-097-1 / IBT-104-1 for category E, Aligned-TaxExemptionCodes.gc
EXEMPTION_REASONS = {
	"DL8.46.1": "Certain financial services",
	"DL8.46.2": "Supply of residential units (lease or sale)",
	"DL8.46.3": "Bare land",
	"DL8.46.4": "Local passenger transport",
}

#: BTAE-09, GoodsType.gc (reverse charge)
RCM_GOODS_TYPES = {
	"DL8.48.8.1": "Gold and diamonds",
	"DL8.48.8.2": "Electronic devices",
	"DL8.48.8.3": "Metal scrap trading",
	"DL8.48.3.1": "Crude or refined oil",
	"DL8.48.3.2": "Unprocessed or processed natural gas",
	"DL8.48.3.3": "Pure hydrocarbons",
}

#: BTAE-13, ItemType.gc
ITEM_TYPES = {"G": "Goods", "S": "Services", "B": "Both"}

#: IBT-008, FreqBilling.gc
BILLING_FREQUENCIES = ("DLY", "WKY", "Q15", "MTH", "Q45", "Q60", "QTR", "YRL", "HYR", "OTH")

#: IBT-081, UNCL4461.gc (subset used in AE)
PAYMENT_MEANS = {
	"1": "Instrument not defined", "10": "In cash", "20": "Cheque", "21": "Banker's draft",
	"30": "Credit transfer", "49": "Direct debit", "54": "Credit card", "55": "Debit card",
	"68": "Online payment service",
}

#: BTAE-15 / BTAE-16 legal registration identifier types (ibr-173-ae, ibr-183-ae)
LEGAL_REGISTRATION_TYPES = {"TL": "Commercial / trade licence", "EID": "Emirates ID", "PAS": "Passport",
	"CD": "Cabinet decision"}

#: BTAE-02 transaction type flag positions (transactiontype.gc), 0-based index
FLAG_FREE_TRADE_ZONE = 0
FLAG_DEEMED_SUPPLY = 1
FLAG_MARGIN_SCHEME = 2
FLAG_SUMMARY = 3
FLAG_CONTINUOUS = 4
FLAG_AGENT_BILLING = 5
FLAG_ECOMMERCE = 6
FLAG_EXPORT = 7

#: Predefined buyer electronic addresses (scheme 0235) of the PINT AE 1.0.5 specification
DEEMED_SUPPLY_ENDPOINT = "9900000097"
NOT_SUBJECT_ENDPOINT = "9900000098"   # buyer not subject to UAE e-invoicing
EXPORT_ENDPOINT = "9900000099"        # export, receiver not registered on Peppol
PREDEFINED_ENDPOINTS = (DEEMED_SUPPLY_ENDPOINT, NOT_SUBJECT_ENDPOINT, EXPORT_ENDPOINT)

#: Document reference type carrying the AED total incl. VAT (BTAE-20)
AED_TOTAL_REFERENCE = "aedtotal-incl-vat"


def flag(flags, position):
	"""True when transaction-type position ``position`` (0-based) is set in an 8-digit flag string."""
	flags = flags or ""
	return len(flags) == 8 and flags[position] == "1"
