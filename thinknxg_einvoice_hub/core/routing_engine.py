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
	settings = {
		field: cp.get(field)
		for field in ("customization_id", "profile_id", "selfbilling_customization_id", "selfbilling_profile_id",
			"endpoint_scheme", "default_currency")
	}
	return get_engine(cp.engine_code, settings)


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
