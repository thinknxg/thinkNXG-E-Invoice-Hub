"""Oman Fawtara / Peppol PINT OM identifiers and code lists.

Sources (checked 2026-11-20; see docs/OMAN_FAWTARA_SPECIFICATION.md for the
requirement-by-requirement table):

* [PINT-OM]  OpenPeppol "PINT OM Billing" v1.0.1 and "PINT OM Self-Billing" v1.0.1,
             https://docs.peppol.eu/poac/om/pint-om/ (PDK 1.4.4, 2026-07-29).
             Schematron ruleset version 1.0.1, "Authority: Tax Authority Oman".
* [OM-SRA]   OpenPeppol "Oman - Solution Reference Architecture", Final v1.0.3, 2026-07-27
             (sections 4, 10 and Appendix D).
* [VAT-LAW]  Oman VAT Law, Royal Decree 121/2020 (5% standard rate, in force 16 April 2021).

Every value can be overridden per Compliance Profile through ``engine_settings``
so a later OTA / OpenPeppol release needs configuration, not a code change.
"""

SPEC_RELEASE = "PINT OM 1.0.1 (ruleset 1.0.1, PDK 1.4.4, 2026-07-29); OM SRA 1.0.3"
RULESET_VERSION = "1.0.1"

# --------------------------------------------------------------------- identifiers [PINT-OM], [OM-SRA 10.1/10.2]
CUSTOMIZATION_ID = "urn:peppol:pint:billing-1@om-1"
PROFILE_ID = "urn:peppol:bis:billing"
SELFBILLING_CUSTOMIZATION_ID = "urn:peppol:pint:selfbilling-1@om-1"
SELFBILLING_PROFILE_ID = "urn:peppol:bis:selfbilling"
#: Peppol participant identifier scheme for Oman VAT registrants [OM-SRA 10.3.1]
ENDPOINT_SCHEME = "0248"
TAX_CURRENCY = "OMR"
#: Tax Data Document. Built and sent to the OTA (via C5) by the accredited service
#: provider (C2/C3); the hub never sends it [OM-SRA 2.2, 5.4].
TDD_DOCUMENT_TYPE = "urn:peppol:schema:om-taxdata:1.0::TaxData##urn:peppol:taxdata:om-1::1.0"
TDD_PROCESS_ID = "urn:peppol:taxreporting"
DOCUMENT_TYPE_IDS = {
	"INVOICE": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2::Invoice##urn:peppol:pint:billing-1@om-1::2.1",
	"CREDIT_NOTE": "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2::CreditNote##urn:peppol:pint:billing-1@om-1::2.1",
	"SELF_BILLING_INVOICE": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2::Invoice##urn:peppol:pint:selfbilling-1@om-1::2.1",
	"SELF_BILLING_CREDIT_NOTE": "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2::CreditNote##urn:peppol:pint:selfbilling-1@om-1::2.1",
}

#: Fixed UUIDv5 namespace for the Invoice UUID (BTOM-002) and the Seller UUID (BTOM-004) [OM-SRA 10.2.3]
UUID_NAMESPACE = "e0bc4ac8-b025-46e5-a76d-0c893fc3027e"

#: "Substitute participant" identifiers (scheme 0248) for receivers outside Peppol [OM-SRA 10.3.1]
SUBSTITUTE_PARTICIPANTS = {
	"DEEMED_SUPPLY_NOT_SHARED": "997770000096",
	"EXPORT": "997770000097",
	"IMPORT_SELF_BILLING_OUT_OF_SCOPE": "997770000098",
	"B2C_OR_PROFIT_MARGIN": "997770000099",
	"BUYER_NOT_ON_PEPPOL": "997770000095",
}
B2C_PARTICIPANT = SUBSTITUTE_PARTICIPANTS["B2C_OR_PROFIT_MARGIN"]
#: fixed buyer values C2 uses on B2C invoices [OM-SRA 4.3]
B2C_BUYER_NAME = "General customer"

# --------------------------------------------------------------------- document types (UNCL1001)
TYPE_CODES = {
	"INVOICE": "380",
	"CREDIT_NOTE": "381",
	"SELF_BILLING_INVOICE": "389",
	"SELF_BILLING_CREDIT_NOTE": "261",
}
CODE_TYPES = {v: k for k, v in TYPE_CODES.items()}
CREDIT_TYPES = ("CREDIT_NOTE", "SELF_BILLING_CREDIT_NOTE")
SELF_BILLING = ("SELF_BILLING_INVOICE", "SELF_BILLING_CREDIT_NOTE")
#: type codes that need a reason code and preceding-invoice reference (IBR-023-OM, IBR-032-OM).
#: 383 (debit note) is in the rules; the canonical model has no debit-note type yet.
ADJUSTMENT_CODES = ("381", "383", "261")

# --------------------------------------------------------------------- CL-03-OM transaction type (BTOM-001)
#: 20-position bitmap on cbc:InvoiceTypeCode/@name; positions 16-20 are reserved placeholders
TRANSACTION_TYPES = (
	"FULL_TAX_INVOICE",            # 1
	"SIMPLIFIED_TAX_INVOICE",      # 2
	"SELF_BILLED",                 # 3
	"THIRD_PARTY",                 # 4
	"SUMMARY",                     # 5
	"CONTINUOUS_SUPPLY",           # 6
	"EXPORT",                      # 7
	"DEEMED_SUPPLY",               # 8
	"IMPORT_OF_SERVICES_RCM",      # 9
	"PROFIT_MARGIN",               # 10
	"PROFIT_MARGIN_SELF_INVOICE",  # 11
	"E_COMMERCE",                  # 12
	"IMPORT_OF_GOODS",             # 13
	"SPECIAL_ZONE",                # 14
	"PREPAYMENT",                  # 15
)
FLAG_LENGTH = 20
#: combinations the ruleset forbids (IBR-138..152-OM, IBR-176-OM, CL-03-OM-1); checked before generation
INCOMPATIBLE_TYPES = (
	("FULL_TAX_INVOICE", "SIMPLIFIED_TAX_INVOICE"),
	("SELF_BILLED", "THIRD_PARTY"), ("SELF_BILLED", "EXPORT"), ("SELF_BILLED", "IMPORT_OF_SERVICES_RCM"),
	("SELF_BILLED", "PROFIT_MARGIN"), ("SELF_BILLED", "PROFIT_MARGIN_SELF_INVOICE"), ("SELF_BILLED", "IMPORT_OF_GOODS"),
	("SUMMARY", "CONTINUOUS_SUPPLY"), ("SUMMARY", "EXPORT"), ("SUMMARY", "PROFIT_MARGIN"),
	("SUMMARY", "PROFIT_MARGIN_SELF_INVOICE"), ("SUMMARY", "IMPORT_OF_GOODS"),
	("CONTINUOUS_SUPPLY", "DEEMED_SUPPLY"),
	("EXPORT", "DEEMED_SUPPLY"), ("EXPORT", "IMPORT_OF_SERVICES_RCM"), ("EXPORT", "PROFIT_MARGIN"),
	("EXPORT", "PROFIT_MARGIN_SELF_INVOICE"), ("EXPORT", "IMPORT_OF_GOODS"),
	("PREPAYMENT", "SUMMARY"), ("PREPAYMENT", "DEEMED_SUPPLY"),
)

# --------------------------------------------------------------------- VAT (CL-04-OM, CL-05-OM, CL-10-OM)
CATEGORY_CODES = {
	"STANDARD": "S",
	"ZERO_RATED": "Z",
	"EXEMPT": "E",
	"OUT_OF_SCOPE": "O",
}
#: categories that carry no cbc:Percent (IBR-061/067-OM, ALIGNED-IBRP-E-05/O-05-OM)
NO_RATE_CATEGORIES = ("EXEMPT", "OUT_OF_SCOPE")

EXEMPTION_CODES = {
	"VATEX-OM-01": "Qualifying financial services",
	"VATEX-OM-02": "Educational services and related goods and services",
	"VATEX-OM-03": "Healthcare services and related goods and services",
	"VATEX-OM-04": "Rental of properties for residential purposes",
	"VATEX-OM-05": "Local passenger transport",
	"VATEX-OM-06": "Undeveloped land (bare land)",
	"VATEX-OM-07": "Resale of residential properties",
	"VATEX-OM-08": "Imported goods supplied to diplomatic and consular bodies and international organisations",
	"VATEX-OM-09": "Imports for the Armed Forces and Internal Security Forces",
	"VATEX-OM-10": "Imported supplies for non-profit charities",
	"VATEX-OM-11": "Import of returned goods",
	"VATEX-OM-12": "Imported goods exempt or zero-rated at the final destination point of entry",
}

ZERO_RATING_CODES = {
	"VATZR-OM-01": "Qualifying supply of food items",
	"VATZR-OM-02": "Qualifying supply of medicines and medical equipment",
	"VATZR-OM-03": "Supply of investment gold, silver and platinum",
	"VATZR-OM-04": "International and intra-GCC transport of goods or passengers",
	"VATZR-OM-05": "Services related to international and intra-GCC transport",
	"VATZR-OM-06": "Supply of qualifying air, sea and land means of transport",
	"VATZR-OM-07": "Supply of rescue planes and rescue and assistance boats",
	"VATZR-OM-08": "Supply of oil, oil derivatives and natural gas",
	"VATZR-OM-09": "Export of services",
	"VATZR-OM-10": "Direct export of goods",
	"VATZR-OM-11": "Indirect export of goods",
	"VATZR-OM-12": "Re-export of goods",
	"VATZR-OM-13": "Supply from a Special Zone to a Special Zone, or within a Special Zone",
	"VATZR-OM-14": "Supply from Mainland to Special Zone",
	"VATZR-OM-15": "Customs duty suspension statuses to a Special Zone",
	"VATZR-OM-16": "Special Zone to customs duty suspension statuses",
}

#: CL-11-OM profit-margin item reason (BTOM-025)
PROFIT_MARGIN_CODES = {
	"VATPM-OM-01": "Tangible movable property",
	"VATPM-OM-02": "Antiques",
	"VATPM-OM-03": "Art works",
	"VATPM-OM-04": "Items of scientific, historical or archaeological importance",
	"VATPM-OM-05": "Assets of collectors",
}

#: Standard VAT rate by effective date [VAT-LAW]; ruleset 1.0.1 fixes 5 (ALIGNED-IBRP-S-05-OM)
STANDARD_RATE_SCHEDULE = (("2021-04-16", "5"),)

# --------------------------------------------------------------------- other code lists
#: CL-02-OM reasons for credit / debit notes (BTOM-032)
CREDIT_REASON_CODES = {
	"CAN": "Cancellation or return",
	"VAT": "Change in VAT treatment",
	"VAL": "Change in value",
	"QTY": "Change in quantity",
	"OTH": "Other",
}

#: CL-06-OM party identifier scheme (BTOM-015 / BTOM-018)
IDENTIFIER_SCHEMES = {
	"CR": "Commercial Registration",
	"TIN": "Tax Identification Number",
	"CID": "Civil ID",
	"PASNUM": "Passport Number",
	"OTHID": "Other Identifier",
	"ICID": "Importer Customs ID",
	"SZLN": "Special Zone License Number",
}

#: CL-13-OM country subdivision, written to cbc:CountrySubentityCode
SUBDIVISIONS = {
	"MO": "Mainland Oman",
	"SEZAD": "Special Economic Zone at Duqm",
	"SHRFZ": "Sohar Free Zone",
	"SLLFZ": "Salalah Free Zone",
	"AFZ": "Al Mazunah Free Zone",
	"OTH": "Other",
}

#: CL-07-OM item type (BTOM-019): ItemSpecificationDocumentReference/DocumentTypeCode
ITEM_TYPES = {"G": "Goods", "S": "Services"}
#: CL-12-OM service type (BTOM-034): ItemSpecificationDocumentReference/ID[@schemeName='MP']
SERVICE_TYPES = {
	"00000000": "Other",
	"64000000": "Financial instruments, products, contracts and agreements",
	"70000000": "Farming, fishing, forestry and wildlife services",
	"71000000": "Mining and oil and gas services",
	"72000000": "Building and facility construction and maintenance services",
	"73000000": "Industrial production and manufacturing services",
	"76000000": "Industrial cleaning services",
	"77000000": "Environmental services",
	"78000000": "Transportation, storage and mail services",
	"80000000": "Management, business and administrative services",
	"81000000": "Engineering, research and technology services",
	"82000000": "Editorial, design, graphic and fine art services",
	"83000000": "Public utilities and public sector services",
	"84000000": "Financial and insurance services",
	"85000000": "Healthcare services",
	"86000000": "Education and training services",
	"90000000": "Travel, food, lodging and entertainment services",
	"91000000": "Personal and domestic services",
	"92000000": "Defense, security and safety services",
	"93000000": "Politics and civic affairs services",
	"94000000": "Organizations and clubs",
}
DEFAULT_SERVICE_TYPE = "00000000"

#: CL-09-OM Incoterms (BTOM-022)
INCOTERMS = ("EXW", "FCA", "CPT", "CIP", "DAP", "DPU", "DDP", "FAS", "FOB", "CFR", "CIF")

#: HS (12 digits, CL-08-OM-HS) and ISIC (6 digits, CL-08-OM-ISIC) value lists are published inside
#: the official resources (codelist/HSCodes-*.gc, codelist/ISIC.gc). The hub checks their format;
#: membership is checked when the official resources are installed (see schematron.py).
HS_LENGTH = 12
ISIC_LENGTH = 6

# --------------------------------------------------------------------- QR code [OM-SRA 4.2, Appendix D]
QR_VERSION = "1.1"
QR_INVOICE_TYPES = {"STANDARD": "01", "PROFIT_MARGIN": "02"}
QR_MAX_BASE64 = 700

# --------------------------------------------------------------------- statuses [OM-SRA 2.3, 8]
#: Peppol MLS response codes used by C3 (invoice) and C5 (TDD)
MLS_CODES = {
	"AP": "Delivered with confirmation",
	"AB": "Delivered without confirmation",
	"RE": "Rejected or delivery failed",
}

#: Oman time zone for "issue date not in the future" (IBR-171-OM)
MUSCAT_UTC_OFFSET_HOURS = 4
