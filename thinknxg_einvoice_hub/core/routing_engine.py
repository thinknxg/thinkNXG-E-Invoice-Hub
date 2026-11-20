"""Routing: which ASP an outbound invoice leaves through, which ERP an inbound one lands in.

Routing is driven by the legal entity (Company Integration Profile). No ERP is
ever wired directly to an ASP.
"""

import frappe

from thinknxg_einvoice_hub.compliance.registry import get_engine
from thinknxg_einvoice_hub.core.company_manager import find_profile_by_tax_id
from thinknxg_einvoice_hub.exceptions import PermanentError


def get_compliance_engine(profile_name):
	"""Engine for a Compliance Profile record."""
	if not profile_name:
		raise PermanentError("No compliance profile is set on the company profile")
	cp = frappe.get_cached_doc("Compliance Profile", profile_name)
	if not cp.enabled:
		raise PermanentError(f"Compliance profile {profile_name} is disabled")
	return get_engine(cp.engine_code, engine_settings(cp))


def engine_settings(cp):
	"""Settings dict for a Compliance Profile: fixed fields, then the JSON engine settings, then tax rules.

	Fixed fields keep their meaning for every country. ``engine_settings`` (JSON) carries country-specific
	options. Active ``tax_rules`` rows become ``standard_rate_schedule`` / ``category_codes`` overrides, so a
	rate change is configuration, not code.
	"""
	settings = {
		field: cp.get(field)
		for field in ("customization_id", "profile_id", "selfbilling_customization_id", "selfbilling_profile_id",
			"endpoint_scheme", "default_currency")
	}
	raw = cp.get("engine_settings")
	if raw:
		try:
			extra = frappe.parse_json(raw)
		except Exception as e:
			raise PermanentError(f"Engine settings of compliance profile {cp.name} are not valid JSON: {e}") from e
		if not isinstance(extra, dict):
			raise PermanentError(f"Engine settings of compliance profile {cp.name} must be a JSON object")
		settings.update(extra)
	rules = [r for r in (cp.get("tax_rules") or []) if r.get("active")]
	if rules:
		schedule = [(str(r.effective_from), str(r.rate)) for r in rules if r.tax_category == "STANDARD"]
		if schedule:
			settings["standard_rate_schedule"] = schedule
		codes = {r.tax_category: r.tax_code for r in rules if r.tax_code}
		if codes:
			settings["category_codes"] = {**(settings.get("category_codes") or {}), **codes}
	return settings


def resolve_outbound_asp(txn, company_profile):
	"""ASP Connection document for an outbound transaction."""
	name = txn.asp_connection or company_profile.asp_connection
	if not name:
		raise PermanentError(f"No ASP connection is designated for company profile {company_profile.name}")
	asp = frappe.get_doc("ASP Connection", name)
	if asp.tenant != txn.tenant:
		raise PermanentError("ASP connection belongs to a different tenant")
	return asp


def resolve_inbound_company(tenant, invoice):
	"""Company profile that should receive an inbound invoice (matched on the buyer)."""
	customer = invoice.get("customer") or {}
	profile = find_profile_by_tax_id(tenant, customer.get("tax_id"), customer.get("tin"))
	if not profile:
		raise PermanentError(
			"No company profile in this tenant matches the buyer on the inbound invoice "
			f"(TRN {customer.get('tax_id') or '-'}, TIN {customer.get('tin') or '-'})"
		)
	return profile
