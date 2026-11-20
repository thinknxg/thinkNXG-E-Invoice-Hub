"""Universal canonical invoice model (schema version 1.0).

Every ERP connector produces this structure and every compliance engine / ASP
adapter consumes it, so N ERPs and M ASPs need N + M integrations, not N x M.

The canonical invoice is a plain JSON-serialisable ``dict``::

    {
      "schema_version": "1.0",
      "document": {
        "document_type": "INVOICE",          # see DOCUMENT_TYPES
        "invoice_kind": "TAX",               # TAX | COMMERCIAL
        "invoice_number": "INV-2026-001",
        "invoice_date": "2026-11-11",
        "due_date": "2026-12-11",
        "tax_point_date": null,
        "currency": "AED",
        "tax_currency": "AED",
        "exchange_rate": 1,                  # document currency -> tax currency
        "direction": "OUTBOUND",             # OUTBOUND | INBOUND
        "transaction_type_flags": "00000000",
        "notes": "",
        "buyer_reference": ""
      },
      "supplier": {PARTY}, "customer": {PARTY},
      "lines": [{LINE}],
      "allowances_charges": [{"is_charge": false, "amount": 0, "reason": "",
                              "tax_category": "STANDARD", "tax_rate": 5}],
      "tax_breakdown": [{"tax_category": "STANDARD", "tax_rate": 5, "taxable_amount": 0,
                         "tax_amount": 0, "exemption_reason": "", "exemption_reason_code": ""}],
      "totals": {"subtotal": 0, "allowance_total": 0, "charge_total": 0, "tax_exclusive": 0,
                 "tax_total": 0, "grand_total": 0, "prepaid_amount": 0, "rounding_amount": 0,
                 "payable_amount": 0},
      "payment": {"means_code": "30", "terms": "", "iban": "", "account_name": ""},
      "delivery": {"date": null, "address": {}},
      "references": {"erp_name": "", "erp_document_id": "", "order_reference": "",
                     "contract_reference": "", "original_invoice_number": "",
                     "original_invoice_date": null},
      "attachments": [{"id": "", "description": "", "filename": "", "mime_type": "", "content_base64": ""}],
      "extensions": {}                       # country- or customer-specific data, passed through
    }

PARTY: legal_name, trading_name, tax_id, tin, endpoint_scheme, legal_registration_id,
       legal_registration_type, legal_registration_authority, address{street, additional_street,
       city, postal_code, subdivision, country}, contact{name, phone, email}
LINE:  line_id, item_code, item_name, description, quantity, unit_code, unit_price,
       price_base_quantity, discount_amount, net_amount, tax_category, tax_rate, tax_amount,
       exemption_reason, exemption_reason_code, commodity_code, item_type
       UAE (PINT AE) only: rcm_goods_type, standard_item_id, standard_item_scheme, service_accounting_code

Optional document keys: uuid, issue_time, invoice_period{start_date, end_date, frequency_code}.
Optional reference keys: original_invoice_uuid, credit_reason_code, credit_reason.
"""

from thinknxg_einvoice_hub.utils import get_path, issue, to_decimal

SCHEMA_VERSION = "1.0"

DOCUMENT_TYPES = ("INVOICE", "CREDIT_NOTE", "SELF_BILLING_INVOICE", "SELF_BILLING_CREDIT_NOTE")
CREDIT_TYPES = ("CREDIT_NOTE", "SELF_BILLING_CREDIT_NOTE")
INVOICE_KINDS = ("TAX", "COMMERCIAL")
DIRECTIONS = ("OUTBOUND", "INBOUND")
TAX_CATEGORIES = ("STANDARD", "ZERO_RATED", "EXEMPT", "OUT_OF_SCOPE", "REVERSE_CHARGE", "MARGIN_SCHEME")

REQUIRED_PATHS = (
	"document.document_type",
	"document.invoice_number",
	"document.invoice_date",
	"document.currency",
	"supplier.legal_name",
	"customer.legal_name",
)
REQUIRED_LINE_FIELDS = ("quantity", "unit_price", "tax_category")


def empty_invoice():
	return {
		"schema_version": SCHEMA_VERSION,
		"document": {"document_type": "INVOICE", "invoice_kind": "TAX", "direction": "OUTBOUND"},
		"supplier": {"address": {}},
		"customer": {"address": {}},
		"lines": [],
		"totals": {},
		"references": {},
	}


def is_canonical(payload):
	"""True when a payload already looks like a canonical invoice."""
	return isinstance(payload, dict) and "schema_version" in payload and isinstance(payload.get("document"), dict)


def validate_structure(inv):
	"""Country-independent structural checks. Returns a list of issue dicts."""
	issues = []
	if not isinstance(inv, dict):
		return [issue("Error", "CAN-000", "", "Canonical invoice must be a JSON object")]

	major = str(inv.get("schema_version") or "").split(".")[0]
	if major != SCHEMA_VERSION.split(".")[0]:
		issues.append(issue("Error", "CAN-001", "schema_version",
			f"Unsupported canonical schema version '{inv.get('schema_version')}', expected {SCHEMA_VERSION}"))

	for path in REQUIRED_PATHS:
		if get_path(inv, path) in (None, ""):
			issues.append(issue("Error", "CAN-002", path, f"{path} is required"))

	doc = inv.get("document") or {}
	if doc.get("document_type") and doc["document_type"] not in DOCUMENT_TYPES:
		issues.append(issue("Error", "CAN-003", "document.document_type",
			f"Unknown document type '{doc['document_type']}'. Allowed: {', '.join(DOCUMENT_TYPES)}"))
	if doc.get("invoice_kind") and doc["invoice_kind"] not in INVOICE_KINDS:
		issues.append(issue("Error", "CAN-004", "document.invoice_kind", "invoice_kind must be TAX or COMMERCIAL"))
	if doc.get("direction") and doc["direction"] not in DIRECTIONS:
		issues.append(issue("Error", "CAN-005", "document.direction", "direction must be OUTBOUND or INBOUND"))

	lines = inv.get("lines")
	if not isinstance(lines, list) or not lines:
		issues.append(issue("Error", "CAN-010", "lines", "At least one invoice line is required"))
		lines = []
	for i, line in enumerate(lines):
		if not isinstance(line, dict):
			issues.append(issue("Error", "CAN-011", f"lines[{i}]", "Invoice line must be an object"))
			continue
		for field in REQUIRED_LINE_FIELDS:
			if line.get(field) in (None, ""):
				issues.append(issue("Error", "CAN-012", f"lines[{i}].{field}", f"{field} is required on every line"))
		for field in ("quantity", "unit_price", "tax_rate", "tax_amount", "net_amount", "discount_amount"):
			if line.get(field) not in (None, "") and to_decimal(line.get(field)) is None:
				issues.append(issue("Error", "CAN-013", f"lines[{i}].{field}", f"{field} must be numeric"))
		if line.get("tax_category") and line["tax_category"] not in TAX_CATEGORIES:
			issues.append(issue("Error", "CAN-014", f"lines[{i}].tax_category",
				f"Unknown tax category '{line['tax_category']}'. Allowed: {', '.join(TAX_CATEGORIES)}"))
		if not (line.get("item_name") or line.get("description")):
			issues.append(issue("Error", "CAN-015", f"lines[{i}].item_name", "Line needs an item name or description"))
	return issues
