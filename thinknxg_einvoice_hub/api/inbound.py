"""Inbound API: authenticated intake of documents received from an ASP.

Use this when the ASP (or an operator) delivers documents with API credentials
rather than a signed webhook, or to load a received document manually.
"""

import frappe
from frappe import _

from thinknxg_einvoice_hub.core.tenant_manager import require_access, resolve_api_tenant
from thinknxg_einvoice_hub.services import invoice_service


@frappe.whitelist(methods=["POST"])
def receive_document(asp_connection, document=None, asp_reference=None, tenant=None):
	"""Register an inbound document (compliance XML or canonical JSON) for one ASP connection."""
	tenant = resolve_api_tenant(tenant)
	require_access(tenant, "Admin", "API")
	if frappe.db.get_value("ASP Connection", asp_connection, "tenant") != tenant:
		frappe.throw(_("ASP connection not found"), frappe.DoesNotExistError)
	if not document:
		frappe.throw(_("'document' is required"))
	name = invoice_service.ingest_inbound(tenant, asp_connection, document, asp_reference)
	return {"transaction": name, "status": frappe.db.get_value("Invoice Transaction", name, "status")}
