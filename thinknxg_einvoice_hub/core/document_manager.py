"""Persistence of transactions, payloads and the audit trail."""

import frappe
from frappe.utils import now_datetime

from thinknxg_einvoice_hub.canonical.invoice_schema import DOCUMENT_TYPES
from thinknxg_einvoice_hub.utils import dumps, fnum, get_path, loads, sha256, to_iso_date


def create_transaction(**values):
	doc = frappe.get_doc({"doctype": "Invoice Transaction", "status": "Received", **values})
	doc.insert(ignore_permissions=True)
	audit(doc, "transaction.created", f"{doc.direction} transaction created")
	return doc


def store_payload(txn, payload_type, content, content_format=None):
	"""Append-only payload store: the original ERP data and every derived form are kept."""
	if isinstance(content, (dict, list)):
		content, content_format = dumps(content), "JSON"
	content = content if isinstance(content, str) else str(content)
	if not content_format:
		content_format = "XML" if content.lstrip().startswith("<") else "Text"
	doc = frappe.get_doc({
		"doctype": "Invoice Payload",
		"tenant": txn.tenant,
		"transaction": txn.name,
		"payload_type": payload_type,
		"content_format": content_format,
		"content": content,
		"sha256": sha256(content),
	})
	doc.insert(ignore_permissions=True)
	return doc.name


def get_payload(txn_name, payload_type, parse=True):
	"""Latest payload of a type; JSON payloads are parsed unless ``parse`` is false."""
	rows = frappe.get_all(
		"Invoice Payload",
		filters={"transaction": txn_name, "payload_type": payload_type},
		fields=["content", "content_format"],
		order_by="creation desc",
		limit=1,
	)
	if not rows:
		return None
	row = rows[0]
	if parse and row["content_format"] == "JSON":
		return loads(row["content"])
	return row["content"]


def apply_canonical_header(txn, inv):
	"""Copy searchable header values from the canonical invoice onto the transaction.

	Values are sanitised so that a malformed ERP document ends in "Validation Failed"
	with clear messages instead of a database error.
	"""
	def text(path, length=140):
		value = get_path(inv, path)
		return str(value)[:length] if value not in (None, "") else None

	doc_type = get_path(inv, "document.document_type")
	txn.update({
		"document_type": doc_type if doc_type in DOCUMENT_TYPES else "INVOICE",
		"invoice_number": text("document.invoice_number"),
		"invoice_date": to_iso_date(get_path(inv, "document.invoice_date")),
		"currency": text("document.currency", 3),
		"subtotal": fnum(get_path(inv, "totals.subtotal")) or 0,
		"tax_total": fnum(get_path(inv, "totals.tax_total")) or 0,
		"grand_total": fnum(get_path(inv, "totals.grand_total")) or 0,
		"supplier_name": text("supplier.legal_name"),
		"supplier_tax_id": text("supplier.tax_id"),
		"customer_name": text("customer.legal_name"),
		"customer_tax_id": text("customer.tax_id"),
		"schema_version": text("schema_version", 20),
	})


def set_validation_messages(txn, issues):
	txn.set("validation_messages", [])
	for item in issues[:200]:
		txn.append("validation_messages", {
			"severity": item.get("severity"),
			"rule_id": item.get("rule_id"),
			"field_path": (item.get("field_path") or "")[:255],
			"message": item.get("message"),
		})


def audit(txn, event, message, level="Info", details=None, tenant=None):
	"""Write an audit entry. ``txn`` may be a document, a name or ``None``."""
	txn_name = getattr(txn, "name", txn)
	tenant = tenant or getattr(txn, "tenant", None)
	if not tenant and txn_name:
		tenant = frappe.db.get_value("Invoice Transaction", txn_name, "tenant")
	user = frappe.session.user
	frappe.get_doc({
		"doctype": "Integration Audit Log",
		"tenant": tenant,
		"transaction": txn_name,
		"event": event,
		"level": level,
		"message": (message or "")[:1000],
		"details": dumps(details) if details else None,
		"actor": user if user and user != "Guest" else None,
		"logged_at": now_datetime(),
	}).insert(ignore_permissions=True)
