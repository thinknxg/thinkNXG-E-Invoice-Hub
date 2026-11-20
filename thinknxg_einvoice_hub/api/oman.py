"""Oman Fawtara API.

Thin, country-checked wrappers over the hub's generic services, so an Oman ERP
integration can call one namespace. Every endpoint resolves the caller's tenant,
checks access, and refuses a company whose compliance profile is not an Oman
engine. Responses never contain credentials.

Endpoints (POST unless noted):
  thinknxg_einvoice_hub.api.oman.validate_invoice     dry run: hub checks + official Schematron if configured
  thinknxg_einvoice_hub.api.oman.generate_document    dry run: PINT OM XML, Invoice UUID, QR payload
  thinknxg_einvoice_hub.api.oman.submit_invoice       queue an invoice / credit note for submission
  thinknxg_einvoice_hub.api.oman.get_status           (GET) lifecycle of one transaction
  thinknxg_einvoice_hub.api.oman.get_document         (GET) stored PINT OM XML of a transaction
  thinknxg_einvoice_hub.api.oman.process_inbound      register a received PINT OM document
  thinknxg_einvoice_hub.api.oman.get_country_profile  (GET) code lists and effective settings
"""

import frappe
from frappe import _

from thinknxg_einvoice_hub.api import get_transaction, json_arg
from thinknxg_einvoice_hub.api import inbound as inbound_api
from thinknxg_einvoice_hub.api import outbound as outbound_api
from thinknxg_einvoice_hub.api import status as status_api
from thinknxg_einvoice_hub.core.company_manager import fill_party_from_profile, resolve_profile
from thinknxg_einvoice_hub.core.routing_engine import get_compliance_engine
from thinknxg_einvoice_hub.core.tenant_manager import require_access, resolve_api_tenant
from thinknxg_einvoice_hub.utils import has_errors

COUNTRY = "OM"


def _oman(tenant, company):
	profile = resolve_profile(tenant, company)
	engine = get_compliance_engine(profile.compliance_profile)
	if engine.country_code != COUNTRY:
		frappe.throw(_("Company profile {0} uses compliance engine {1}, not an Oman engine").format(
			profile.name, engine.code))
	return profile, engine


def _prepare(payload, profile, engine):
	from thinknxg_einvoice_hub.canonical.invoice_schema import is_canonical, validate_structure

	from thinknxg_einvoice_hub.canonical.normalizer import normalize

	if not is_canonical(payload):
		frappe.throw(_("This endpoint accepts canonical invoices only (schema_version is missing)"))
	inv = normalize(payload)
	inv["supplier"] = fill_party_from_profile(inv.get("supplier") or {}, profile)
	inv = engine.enrich(inv)
	return inv, validate_structure(inv)


def _result(engine, issues, **extra):
	errors = [i for i in issues if i["severity"] == "Error"]
	return {
		"success": not errors,
		"country": COUNTRY,
		"profile": engine.code,
		"validation_status": "FAILED" if errors else "PASSED",
		"errors": errors,
		"warnings": [i for i in issues if i["severity"] != "Error"],
		**extra,
	}


@frappe.whitelist(methods=["POST"])
def validate_invoice(invoice=None, company=None, tenant=None):
	"""Normalise and validate without storing anything. Runs the official Schematron when configured."""
	tenant = resolve_api_tenant(tenant)
	profile, engine = _oman(tenant, company)
	inv, issues = _prepare(json_arg(invoice, "invoice"), profile, engine)
	if not has_errors(issues):
		issues += engine.validate(inv)
	if not has_errors(issues):
		issues += engine.validate_document(engine.generate_document(inv), inv)
	return _result(engine, issues, canonical=inv)


@frappe.whitelist(methods=["POST"])
def generate_document(invoice=None, company=None, tenant=None):
	"""Return the PINT OM XML for a canonical invoice without storing or sending it."""
	tenant = resolve_api_tenant(tenant)
	profile, engine = _oman(tenant, company)
	inv, issues = _prepare(json_arg(invoice, "invoice"), profile, engine)
	if not has_errors(issues):
		issues += engine.validate(inv)
	if has_errors(issues):
		return _result(engine, issues)
	document = engine.generate_document(inv)
	issues += engine.validate_document(document, inv)
	return _result(engine, issues, document=document["content"], document_uuid=document["document_uuid"],
		seller_uuid=(inv.get("supplier") or {}).get("uuid"),
		qr_base64=((inv.get("extensions") or {}).get("om") or {}).get("qr_base64"))


@frappe.whitelist(methods=["POST"])
def submit_invoice(invoice=None, company=None, erp_connection=None, erp_document_id=None, tenant=None):
	"""Queue an Oman invoice or credit note. Processing continues in the background; poll get_status."""
	resolved = resolve_api_tenant(tenant)
	require_access(resolved, "Admin", "API")
	_oman(resolved, company)
	return outbound_api.submit_invoice(invoice=invoice, company=company, erp_connection=erp_connection,
		erp_document_id=erp_document_id, tenant=tenant)


@frappe.whitelist()
def get_status(transaction=None, erp_document_id=None, invoice_number=None, tenant=None):
	"""Lifecycle of one transaction. ``fta_status`` is the Oman Tax Authority reporting status
	(TDD MLS from the provider); ``delivery_status`` is Peppol delivery to the buyer (invoice MLS)."""
	data = status_api.get_status(transaction=transaction, erp_document_id=erp_document_id,
		invoice_number=invoice_number, tenant=tenant)
	if data.get("country_code") not in (None, "", COUNTRY):
		frappe.throw(_("Transaction {0} is not an Oman transaction").format(data["transaction"]))
	data["tax_authority_reporting_status"] = data.get("fta_status")
	return data


@frappe.whitelist()
def get_document(transaction, payload_type="Compliance Document", tenant=None):
	resolved = resolve_api_tenant(tenant)
	txn = get_transaction(transaction, resolved)
	if txn.get("country_code") not in (None, "", COUNTRY):
		frappe.throw(_("Transaction {0} is not an Oman transaction").format(txn.name))
	return status_api.get_document(transaction=transaction, payload_type=payload_type, tenant=tenant)


@frappe.whitelist(methods=["POST"])
def process_inbound(asp_connection, document=None, asp_reference=None, tenant=None):
	"""Register a PINT OM document received from the Oman accredited provider (same as the generic inbound API)."""
	return inbound_api.receive_document(asp_connection=asp_connection, document=document,
		asp_reference=asp_reference, tenant=tenant)


@frappe.whitelist()
def get_country_profile(company=None, tenant=None):
	tenant = resolve_api_tenant(tenant)
	_profile, engine = _oman(tenant, company)
	info = engine.get_country_profile()
	settings = info.get("settings") or {}
	# no secrets and no server paths for tenant users
	info["settings"] = {k: (bool(v) if k.endswith("_dir") else v) for k, v in settings.items()
		if "secret" not in k and "password" not in k}
	return info
