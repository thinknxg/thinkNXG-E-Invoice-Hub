"""ASP API: provider directory, credential checks and document retrieval."""

import base64

import frappe
from frappe import _

from thinknxg_einvoice_hub.api import get_transaction
from thinknxg_einvoice_hub.asp_connectors import base_adapter as asp
from thinknxg_einvoice_hub.asp_connectors.adapter_registry import get_adapter
from thinknxg_einvoice_hub.core import document_manager as dm
from thinknxg_einvoice_hub.core.tenant_manager import require_access, resolve_api_tenant


def _connection(name, tenant):
	if not name or frappe.db.get_value("ASP Connection", name, "tenant") != tenant:
		frappe.throw(_("ASP connection not found"), frappe.DoesNotExistError)
	return frappe.get_doc("ASP Connection", name)


@frappe.whitelist()
def providers():
	"""The ASP directory: accreditation, integration status and production readiness are separate facts."""
	return frappe.get_all(
		"UAE Accredited Service Provider",
		filters={"enabled": 1},
		fields=["asp_code", "asp_name", "legal_name", "accreditation_number", "accreditation_status",
			"integration_status", "adapter_type", "adapter", "sandbox_tested", "production_verified",
			"supported_capabilities"],
		order_by="asp_name asc",
	)


@frappe.whitelist(methods=["POST"])
def verify_credentials(asp_connection, tenant=None):
	tenant = resolve_api_tenant(tenant)
	require_access(tenant, "Admin")
	return {"result": get_adapter(_connection(asp_connection, tenant)).verify_credentials()}


@frappe.whitelist()
def readiness(asp_connection, tenant=None):
	"""Configuration readiness of a contract-pending provider (e.g. Microvista). Makes no external call."""
	tenant = resolve_api_tenant(tenant)
	adapter = get_adapter(_connection(asp_connection, tenant))
	if hasattr(adapter, "readiness"):
		return adapter.readiness()
	return {"ready_for_sandbox": True, "capabilities": sorted(adapter.capabilities)}


@frappe.whitelist(methods=["POST"])
def fetch_document(transaction, kind="xml", tenant=None):
	"""Retrieve the XML or PDF the ASP holds for a submitted document and keep a copy in the hub."""
	tenant = resolve_api_tenant(tenant)
	require_access(tenant, "Admin", "API")
	txn = get_transaction(transaction, tenant)
	if not txn.asp_reference or not txn.asp_connection:
		frappe.throw(_("This transaction has not been submitted to an ASP"))
	adapter = get_adapter(txn.asp_connection)
	kind = (kind or "xml").lower()
	if kind == "xml":
		adapter.require(asp.CAP_XML)
		content = adapter.get_document_xml(txn.asp_reference)
		content = content.decode("utf-8") if isinstance(content, bytes) else str(content)
		dm.store_payload(txn, "ASP Document", content, "XML")
		return {"transaction": txn.name, "kind": "xml", "content": content}
	if kind == "pdf":
		adapter.require(asp.CAP_PDF)
		content = adapter.get_document_pdf(txn.asp_reference)
		if not isinstance(content, bytes) or content[:4] != b"%PDF":
			frappe.throw(_("The provider did not return a PDF document"))
		file = frappe.get_doc({"doctype": "File", "file_name": f"{txn.name}.pdf", "is_private": 1,
			"attached_to_doctype": "Invoice Transaction", "attached_to_name": txn.name, "content": content})
		try:
			file.insert(ignore_permissions=True)
		except Exception:
			frappe.throw(_("The provider's response is not a readable PDF document"))
		return {"transaction": txn.name, "kind": "pdf", "file_url": file.file_url,
			"content_base64": base64.b64encode(content).decode()}
	frappe.throw(_("kind must be xml or pdf"))
