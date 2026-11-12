"""Outbound API: ERPs hand invoices to the hub."""

import frappe
from frappe import _

from thinknxg_einvoice_hub.api import json_arg
from thinknxg_einvoice_hub.core.company_manager import resolve_profile
from thinknxg_einvoice_hub.core.tenant_manager import require_access, resolve_api_tenant
from thinknxg_einvoice_hub.erp_connectors import base_connector as erp
from thinknxg_einvoice_hub.erp_connectors.connector_registry import get_connector
from thinknxg_einvoice_hub.services import invoice_service


def _own_erp_connection(name, tenant):
	if name and frappe.db.get_value("ERP Connection", name, "tenant") != tenant:
		frappe.throw(_("ERP connection not found"), frappe.DoesNotExistError)
	return name


@frappe.whitelist(methods=["POST"])
def submit_invoice(invoice=None, company=None, erp_connection=None, erp_document_id=None, tenant=None):
	"""Submit one invoice or credit note.

	``invoice`` is either a canonical invoice (it carries ``schema_version``) or the ERP's own
	JSON, which is then mapped with the Mapping Configuration of ``erp_connection``.
	Returns immediately; processing continues in the background. Poll ``status.get_status``
	or register a status callback on the ERP connection.
	"""
	tenant = resolve_api_tenant(tenant)
	require_access(tenant, "Admin", "API")
	payload = json_arg(invoice, "invoice")
	profile = resolve_profile(tenant, company)
	erp_connection = _own_erp_connection(erp_connection, tenant)
	if not erp_document_id and isinstance(payload, dict):
		erp_document_id = (payload.get("references") or {}).get("erp_document_id")
	name = invoice_service.ingest_outbound(tenant, profile.name, payload, erp_connection, erp_document_id)
	return {"transaction": name, "status": frappe.db.get_value("Invoice Transaction", name, "status")}


@frappe.whitelist(methods=["POST"])
def fetch_and_submit(erp_document_id, erp_connection=None, company=None, tenant=None):
	"""Ask the hub to pull one document from the ERP and transmit it."""
	tenant = resolve_api_tenant(tenant)
	require_access(tenant, "Admin", "API")
	profile = resolve_profile(tenant, company)
	erp_connection = _own_erp_connection(erp_connection, tenant) or profile.erp_connection
	if not erp_connection:
		frappe.throw(_("No ERP connection is configured for this company"))
	connector = get_connector(erp_connection)
	connector.require(erp.CAP_FETCH_INVOICE)
	payload = connector.fetch_invoice(erp_document_id)
	name = invoice_service.ingest_outbound(tenant, profile.name, payload, erp_connection, erp_document_id)
	return {"transaction": name, "status": frappe.db.get_value("Invoice Transaction", name, "status")}


@frappe.whitelist(methods=["POST"])
def validate_invoice(invoice=None, company=None, tenant=None):
	"""Dry run: normalise and validate a canonical invoice without storing or transmitting it."""
	from thinknxg_einvoice_hub.canonical.invoice_schema import is_canonical, validate_structure
	from thinknxg_einvoice_hub.canonical.normalizer import normalize
	from thinknxg_einvoice_hub.core.company_manager import fill_party_from_profile
	from thinknxg_einvoice_hub.core.routing_engine import get_compliance_engine
	from thinknxg_einvoice_hub.utils import has_errors

	tenant = resolve_api_tenant(tenant)
	payload = json_arg(invoice, "invoice")
	if not is_canonical(payload):
		frappe.throw(_("validate_invoice accepts canonical invoices only (schema_version is missing)"))
	profile = resolve_profile(tenant, company)
	engine = get_compliance_engine(profile.compliance_profile)
	inv = normalize(payload)
	inv["supplier"] = fill_party_from_profile(inv.get("supplier") or {}, profile)
	inv = engine.enrich(inv)
	issues = validate_structure(inv)
	if not has_errors(issues):
		issues += engine.validate(inv)
	return {"valid": not has_errors(issues), "messages": issues, "canonical": inv}
