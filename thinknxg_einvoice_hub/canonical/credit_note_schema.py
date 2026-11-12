"""Credit-note specific rules on top of the canonical invoice."""

from thinknxg_einvoice_hub.canonical.invoice_schema import CREDIT_TYPES
from thinknxg_einvoice_hub.utils import get_path, issue


def is_credit_note(inv):
	return get_path(inv, "document.document_type") in CREDIT_TYPES


def validate_credit_note(inv):
	if not is_credit_note(inv):
		return []
	if not get_path(inv, "references.original_invoice_number"):
		return [issue("Error", "CAN-020", "references.original_invoice_number",
			"A credit note must reference the original invoice number")]
	return []
