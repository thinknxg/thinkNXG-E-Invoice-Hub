"""Operational statistics for dashboards and health checks."""

import frappe
from frappe.query_builder.functions import Count
from frappe.utils import add_to_date, cint, now_datetime

from thinknxg_einvoice_hub.core.tenant_manager import is_hub_admin, resolve_api_tenant


@frappe.whitelist()
def get_stats(tenant=None, days=30):
	"""Transaction counts by direction and status for one tenant (all tenants for hub administrators)."""
	since = add_to_date(now_datetime(), days=-max(cint(days), 1))
	filters = {"creation": [">", since]}
	tenant_filter = None
	if tenant or not is_hub_admin():
		tenant_filter = filters["tenant"] = resolve_api_tenant(tenant)
	table = frappe.qb.DocType("Invoice Transaction")
	query = (
		frappe.qb.from_(table)
		.select(table.direction, table.status, Count(table.name).as_("total"))
		.where(table.creation > since)
		.groupby(table.direction, table.status)
	)
	if tenant_filter:
		query = query.where(table.tenant == tenant_filter)
	rows = query.run(as_dict=True)
	summary = {"Outbound": {}, "Inbound": {}}
	for row in rows:
		summary.setdefault(row["direction"], {})[row["status"]] = row["total"]
	return {
		"period_days": cint(days),
		"by_status": summary,
		"retry_queue": frappe.db.count("Invoice Transaction", {**filters, "status": "Retrying"}),
		"erp_out_of_sync": frappe.db.count("Invoice Transaction", {**filters, "erp_sync_status": "Failed"}),
	}


@frappe.whitelist()
def get_dashboard(company=None, erp_connection=None, asp_connection=None, from_date=None, to_date=None,
		document_type=None, fta_status=None, delivery_status=None, tenant=None):
	"""Figures for the Universal Integration Dashboard, limited to the caller's tenants."""
	from thinknxg_einvoice_hub.core.tenant_manager import get_user_tenants

	scope = {}
	if tenant:
		scope["tenant"] = resolve_api_tenant(tenant)
	elif not is_hub_admin():
		tenants = get_user_tenants()
		if not tenants:
			frappe.throw(frappe._("This user is not assigned to any tenant"), frappe.PermissionError)
		scope["tenant"] = ["in", tenants]

	txn = dict(scope)
	for field, value in (("company_profile", company), ("erp_connection", erp_connection),
			("asp_connection", asp_connection), ("document_type", document_type), ("fta_status", fta_status),
			("delivery_status", delivery_status)):
		if value:
			txn[field] = value
	if from_date and to_date:
		txn["creation"] = ["between", [from_date, f"{to_date} 23:59:59"]]
	elif from_date:
		txn["creation"] = [">=", from_date]
	elif to_date:
		txn["creation"] = ["<=", f"{to_date} 23:59:59"]

	def count(doctype, base, **extra):
		return frappe.db.count(doctype, {**base, **extra})

	t = "Invoice Transaction"
	return {
		"connections": {
			"erp_total": count("ERP Connection", scope),
			"erp_active": count("ERP Connection", scope, enabled=1),
			"asp_configured": count("ASP Connection", scope, enabled=1),
			"asp_production_ready": frappe.db.count("UAE Accredited Service Provider",
				{"production_verified": 1, "enabled": 1}),
			"asp_in_directory": frappe.db.count("UAE Accredited Service Provider", {"enabled": 1}),
		},
		"invoices": {
			"received": count(t, txn),
			"submitted": count(t, txn, asp_submission_status=["in", ["Submitted", "Accepted", "Rejected"]]),
			"asp_accepted": count(t, txn, asp_submission_status="Accepted"),
			"asp_rejected": count(t, txn, asp_submission_status="Rejected"),
			"fta_reported": count(t, txn, **({} if fta_status else {"fta_status": "Reported"})) if not fta_status
			else count(t, {**txn, "fta_status": "Reported"}) if fta_status == "Reported" else 0,
			"fta_rejected": count(t, {**txn, "fta_status": "Rejected"}) if fta_status in (None, "", "Rejected") else 0,
			"delivery_failed": count(t, {**txn, "delivery_status": "Failed"})
			if delivery_status in (None, "", "Failed") else 0,
			"validation_failed": count(t, txn, status="Validation Failed"),
			"pending_sync": count(t, txn, erp_sync_status=["in", ["Pending", "Failed"]]),
			"errors": count(t, txn, status=["in", ["Failed", "Retrying"]]),
		},
		"api_failures": count("Integration Log", scope, result="Failure"),
	}
