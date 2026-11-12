"""Reconciliation: keep ERP, hub and ASP statuses in step."""

import frappe
from frappe.utils import add_to_date, cint, now_datetime

from thinknxg_einvoice_hub.core import document_manager as dm
from thinknxg_einvoice_hub.core.tenant_manager import resolve_api_tenant
from thinknxg_einvoice_hub.erp_connectors import base_connector as erp
from thinknxg_einvoice_hub.erp_connectors.connector_registry import get_connector
from thinknxg_einvoice_hub.utils import loads


def _batch(field, default):
	return cint(frappe.db.get_single_value("E-Invoice Hub Settings", field)) or default


def sync_submitted_statuses():
	"""Scheduler: ask ASPs about documents that are submitted but not yet delivered."""
	from thinknxg_einvoice_hub.services.invoice_service import refresh_asp_status

	names = frappe.get_all(
		"Invoice Transaction",
		filters={"direction": "Outbound", "asp_reference": ["is", "set"]},
		or_filters={"status": "Submitted", "fta_status": "Pending", "delivery_status": "Pending"},
		pluck="name",
		order_by="modified asc",
		limit=_batch("status_sync_batch", 100),
	)
	for name in names:
		try:
			refresh_asp_status(name)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title=f"E-Invoice Hub status sync: {name}", message=frappe.get_traceback())
	return len(names)


def poll_incoming_invoices():
	"""Scheduler: collect incoming invoices from ASPs that offer a retrieval endpoint (polling-only providers)."""
	from thinknxg_einvoice_hub.asp_connectors import base_adapter as asp
	from thinknxg_einvoice_hub.asp_connectors.adapter_registry import get_adapter
	from thinknxg_einvoice_hub.services.invoice_service import ingest_inbound
	from thinknxg_einvoice_hub.utils import dumps, get_path, sha256

	total = 0
	for name in frappe.get_all("ASP Connection", filters={"enabled": 1}, pluck="name"):
		try:
			conn = frappe.get_doc("ASP Connection", name)
			adapter = get_adapter(conn)
			if not adapter.supports(asp.CAP_INCOMING):
				continue
			id_path = ((getattr(adapter, "rest", None) or {}).get("webhook") or {}).get("document_id_path") or "id"
			for item in adapter.get_incoming_invoices():
				reference = get_path(item, id_path) if isinstance(item, dict) else None
				ingest_inbound(conn.tenant, conn.name, item, asp_reference=str(reference or sha256(dumps(item))[:32]))
				total += 1
			frappe.db.commit()
		except Exception as e:
			frappe.db.rollback()
			dm.audit(None, "asp.incoming_poll_failed", f"{name}: {e}", level="Error",
				tenant=frappe.db.get_value("ASP Connection", name, "tenant"))
			frappe.db.commit()
	return total


def retry_erp_sync():
	"""Scheduler: resend statuses the ERP did not accept the first time."""
	from thinknxg_einvoice_hub.services.invoice_service import sync_erp_status

	names = frappe.get_all(
		"Invoice Transaction",
		filters={"erp_sync_status": "Failed", "direction": "Outbound",
			"modified": [">", add_to_date(now_datetime(), days=-7)]},
		pluck="name",
		limit=100,
	)
	for name in names:
		sync_erp_status(name)
		frappe.db.commit()
	return len(names)


def poll_erp_connections():
	"""Scheduler: retrieve pending invoices from ERPs that are configured for scheduled retrieval."""
	for name in frappe.get_all("ERP Connection", filters={"enabled": 1, "polling_enabled": 1}, pluck="name"):
		try:
			poll_connection(name)
			frappe.db.commit()
		except Exception as e:
			frappe.db.rollback()
			dm.audit(None, "erp.poll_failed", f"{name}: {e}", level="Error",
				tenant=frappe.db.get_value("ERP Connection", name, "tenant"))
			frappe.db.commit()


def poll_connection(connection_name):
	from thinknxg_einvoice_hub.services.invoice_service import ingest_outbound

	conn = frappe.get_doc("ERP Connection", connection_name)
	connector = get_connector(conn)
	if not (connector.supports(erp.CAP_FETCH_PENDING) and connector.supports(erp.CAP_FETCH_INVOICE)):
		return 0
	profiles = frappe.get_all(
		"Company Integration Profile",
		filters={"tenant": conn.tenant, "erp_connection": conn.name, "enabled": 1},
		fields=["name", "tax_id"],
	)
	if not profiles:
		return 0
	started = now_datetime()
	filters = dict(loads(conn.polling_filters, {}) or {})
	filters.setdefault("limit", _batch("poll_batch_size", 50))
	if conn.last_polled_on:
		filters.setdefault("modified_after", conn.last_polled_on)

	count = 0
	for document_id in connector.fetch_pending_invoices(filters):
		if frappe.db.exists("Invoice Transaction", {"erp_connection": conn.name, "erp_document_id": str(document_id)}):
			continue
		payload = connector.fetch_invoice(document_id)
		profile = profiles[0]["name"]
		if len(profiles) > 1:
			supplier_tax_id = (connector.normalize_invoice(payload).get("supplier") or {}).get("tax_id")
			match = [p["name"] for p in profiles if p["tax_id"] and p["tax_id"] == supplier_tax_id]
			if not match:
				dm.audit(None, "erp.poll_skipped", f"{conn.name}: no company profile matches ERP document {document_id}",
					level="Warning", tenant=conn.tenant)
				continue
			profile = match[0]
		ingest_outbound(conn.tenant, profile, payload, erp_connection=conn.name, erp_document_id=document_id)
		count += 1
	conn.db_set("last_polled_on", started, update_modified=False)
	return count


@frappe.whitelist()
def get_report(tenant=None, stuck_hours=2):
	"""Transactions that need attention: stuck in flight, undelivered, or out of step with the ERP."""
	tenant = resolve_api_tenant(tenant)
	fields = ["name", "direction", "status", "invoice_number", "erp_document_id", "asp_reference", "erp_sync_status",
		"last_error", "modified"]
	cutoff = add_to_date(now_datetime(), hours=-max(cint(stuck_hours), 1))
	base = {"tenant": tenant}
	return {
		"stuck_in_flight": frappe.get_all("Invoice Transaction", fields=fields, limit=200,
			filters={**base, "status": ["in", ["Received", "Normalized"]], "modified": ["<", cutoff]}),
		"awaiting_delivery": frappe.get_all("Invoice Transaction", fields=fields, limit=200,
			filters={**base, "status": "Submitted", "modified": ["<", cutoff]}),
		"failed": frappe.get_all("Invoice Transaction", fields=fields, limit=200,
			filters={**base, "status": ["in", ["Failed", "Validation Failed", "Rejected"]]}),
		"erp_out_of_sync": frappe.get_all("Invoice Transaction", fields=fields, limit=200,
			filters={**base, "erp_sync_status": "Failed"}),
	}
