"""Integration Log: one record per call to an external API, with credentials masked."""

import frappe
from frappe.utils import add_to_date, cint, now_datetime

from thinknxg_einvoice_hub.utils import dumps


def write(entry, tenant=None, asp_connection=None, erp_connection=None):
	"""``entry`` comes from ``ASPRestEngine`` and is already masked."""
	try:
		frappe.get_doc({
			"doctype": "Integration Log",
			"tenant": tenant,
			"asp_connection": asp_connection,
			"erp_connection": erp_connection,
			"operation": entry.get("operation"),
			"transaction": entry.get("transaction"),
			"result": entry.get("result") or "Failure",
			"http_method": entry.get("http_method"),
			"http_status": entry.get("http_status"),
			"duration_ms": entry.get("duration_ms"),
			"url": (entry.get("url") or "")[:500],
			"error": (entry.get("error") or "")[:1000] or None,
			"request": dumps({"headers": entry.get("request_headers"), "body": entry.get("request")})[:60000],
			"response": dumps(entry.get("response"))[:60000],
			"logged_at": now_datetime(),
		}).insert(ignore_permissions=True)
		# keep the record even if the surrounding operation fails and rolls back: failed calls are the
		# ones an operator most needs to see. Callers commit their own state before contacting a provider.
		frappe.db.commit()
	except Exception:
		frappe.log_error(title="E-Invoice Hub: integration log", message=frappe.get_traceback())


def purge_old_logs():
	"""Scheduler: drop integration logs older than the retention period."""
	days = cint(frappe.db.get_single_value("E-Invoice Hub Settings", "log_retention_days")) or 90
	frappe.db.delete("Integration Log", {"logged_at": ["<", add_to_date(now_datetime(), days=-days)]})
