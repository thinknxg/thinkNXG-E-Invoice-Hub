"""Company Integration Profile helpers: legal entities and their identifiers."""

import frappe
from frappe import _

from thinknxg_einvoice_hub.utils import deep_merge


def get_profile(name, tenant=None):
	profile = frappe.get_doc("Company Integration Profile", name)
	if tenant and profile.tenant != tenant:
		frappe.throw(_("Company profile {0} does not belong to this tenant").format(name), frappe.PermissionError)
	if not profile.enabled:
		frappe.throw(_("Company profile {0} is disabled").format(name))
	return profile


def resolve_profile(tenant, company=None):
	"""Find a company profile by record name, TRN or legal name within a tenant."""
	if company:
		for filters in ({"name": company}, {"tax_id": company}, {"company_name": company}):
			name = frappe.db.get_value("Company Integration Profile", {**filters, "tenant": tenant, "enabled": 1}, "name")
			if name:
				return frappe.get_doc("Company Integration Profile", name)
		frappe.throw(_("No enabled company profile matches '{0}'").format(company))
	names = frappe.get_all("Company Integration Profile", filters={"tenant": tenant, "enabled": 1}, pluck="name", limit=2)
	if len(names) == 1:
		return frappe.get_doc("Company Integration Profile", names[0])
	frappe.throw(_("Pass the 'company' parameter (profile ID, TRN or legal name)"))


def find_profile_by_tax_id(tenant, tax_id=None, tin=None):
	for field, value in (("tax_id", tax_id), ("tin", tin)):
		if value:
			name = frappe.db.get_value("Company Integration Profile", {"tenant": tenant, field: value, "enabled": 1}, "name")
			if name:
				return frappe.get_doc("Company Integration Profile", name)
	return None


def profile_party(profile):
	"""Canonical party block built from the company profile.

	Fields added for Oman (address line 3, contact) and the UAE (legal registration authority) are only
	included when set, so profiles without
	them produce exactly the same party block as before.
	"""
	party = _base_party(profile)
	if profile.get("address_line"):
		party["address"]["address_line"] = profile.address_line
	if profile.get("legal_registration_authority"):
		party["legal_registration_authority"] = profile.legal_registration_authority
	contact = {k: profile.get(f) for k, f in (("name", "contact_name"), ("phone", "contact_phone"),
		("email", "contact_email")) if profile.get(f)}
	if contact:
		party["contact"] = contact
	return party


def _base_party(profile):
	return {
		"legal_name": profile.company_name,
		"trading_name": profile.trading_name,
		"tax_id": profile.tax_id,
		"tin": profile.tin,
		"legal_registration_id": profile.legal_registration_id,
		"legal_registration_type": profile.legal_registration_type,
		"address": {
			"street": profile.street,
			"additional_street": profile.additional_street,
			"city": profile.city,
			"postal_code": profile.postal_code,
			"subdivision": profile.subdivision,
			"country": (profile.country_code or "").upper() or None,
		},
	}


def fill_party_from_profile(party, profile):
	"""Fill gaps in an invoice party from the profile (ERP values win where present)."""
	return deep_merge(party, profile_party(profile))
