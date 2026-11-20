"""Status API: track, inspect and re-run transactions."""

import frappe
from frappe import _
from frappe.utils import cint

from thinknxg_einvoice_hub.api import get_transaction
from thinknxg_einvoice_hub.core import document_manager as dm
from thinknxg_einvoice_hub.core.tenant_manager import require_access, resolve_api_tenant
from thinknxg_einvoice_hub.services import invoice_service

SUMMARY_FIELDS = ["name", "direction", "document_type", "status", "invoice_number", "invoice_date", "currency",
	"grand_total", "supplier_name", "customer_name", "company_profile", "erp_document_id", "erp_sync_status",
	"asp_reference", "asp_status", "asp_message", "retry_count", "next_retry_at", "last_error", "submitted_at",
	"delivered_at", "duplicate_of", "creation", "modified", "validation_status", "asp_submission_status",
	"asp_error_code", "fta_status", "fta_reference", "fta_message", "delivery_status", "delivery_reference",
	"delivery_message", "accredited_provider", "source_erp", "country_code", "document_uuid"]
PAYLOAD_TYPES = ("Source ERP", "Canonical", "Compliance Document", "ASP Response", "ASP Inbound", "ERP Response",
	"ASP Document")


def _summary(txn):
	data = {field: txn.get(field) for field in SUMMARY_FIELDS}
	data["transaction"] = data.pop("name")
	data["messages"] = [
		{"severity": m.severity, "rule_id": m.rule_id, "field": m.field_path, "message": m.message}
		for m in txn.validation_messages
	]
	return data


@frappe.whitelist()
def get_status(transaction=None, erp_document_id=None, invoice_number=None, tenant=None):
	"""Status of one transaction, looked up by hub ID, ERP document ID or invoice number."""
	tenant = resolve_api_tenant(tenant)
	if not transaction:
		filters = {"tenant": tenant}
		if erp_document_id:
			filters["erp_document_id"] = str(erp_document_id)
		elif invoice_number:
			filters["invoice_number"] = invoice_number
		else:
			frappe.throw(_("Pass transaction, erp_document_id or invoice_number"))
		transaction = frappe.db.get_value("Invoice Transaction", filters, "name", order_by="creation desc")
	return _summary(get_transaction(transaction, tenant))


@frappe.whitelist()
def list_transactions(status=None, direction=None, company=None, modified_after=None, start=0, limit=50, tenant=None,
		country=None):
	tenant = resolve_api_tenant(tenant)
	filters = {"tenant": tenant}
	if country:
		filters["country_code"] = country
	if status:
		filters["status"] = status
	if direction:
		filters["direction"] = direction
	if company:
		filters["company_profile"] = company
	if modified_after:
		filters["modified"] = [">", modified_after]
	return frappe.get_all(
		"Invoice Transaction",
		filters=filters,
		fields=[f for f in SUMMARY_FIELDS if f != "last_error"],
		order_by="modified desc",
		limit_start=cint(start),
		limit_page_length=min(cint(limit) or 50, 500),
	)


@frappe.whitelist()
def get_document(transaction, payload_type="Compliance Document", tenant=None):
	"""Return a stored payload, e.g. the generated compliance XML or the canonical JSON."""
	tenant = resolve_api_tenant(tenant)
	if payload_type not in PAYLOAD_TYPES:
		frappe.throw(_("payload_type must be one of: {0}").format(", ".join(PAYLOAD_TYPES)))
	txn = get_transaction(transaction, tenant)
	content = dm.get_payload(txn.name, payload_type, parse=False)
	if content is None:
		frappe.throw(_("No {0} payload is stored for this transaction").format(payload_type), frappe.DoesNotExistError)
	return {"transaction": txn.name, "payload_type": payload_type, "content": content}


@frappe.whitelist(methods=["POST"])
def reprocess(transaction, renormalize=1, tenant=None):
	"""Re-run a transaction, e.g. after fixing a mapping or a company profile."""
	tenant = resolve_api_tenant(tenant)
	require_access(tenant, "Admin", "API")
	txn = get_transaction(transaction, tenant)
	invoice_service.reprocess(txn.name, renormalize=bool(cint(renormalize)))
	return {"transaction": txn.name, "queued": True}


@frappe.whitelist(methods=["POST"])
def refresh_status(transaction, tenant=None):
	"""Ask the ASP for the latest status of a submitted document."""
	tenant = resolve_api_tenant(tenant)
	txn = get_transaction(transaction, tenant)
	return {"transaction": txn.name, "status": invoice_service.refresh_asp_status(txn.name)}


@frappe.whitelist(methods=["POST"])
def cancel(transaction, tenant=None):
	"""Stop processing a transaction that has not been submitted to an ASP."""
	from thinknxg_einvoice_hub.core.transaction_manager import REPROCESSABLE, set_status

	tenant = resolve_api_tenant(tenant)
	require_access(tenant, "Admin", "API")
	txn = get_transaction(transaction, tenant)
	if txn.status not in REPROCESSABLE:
		frappe.throw(_("A transaction in status {0} cannot be cancelled").format(txn.status))
	set_status(txn, "Cancelled", "Cancelled by user")
	return {"transaction": txn.name, "status": "Cancelled"}
