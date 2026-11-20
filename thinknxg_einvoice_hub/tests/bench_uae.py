"""Bench integration checks for the UAE PINT AE 1.0.5 engine (needs a site with the app installed).

    bench --site <site> execute thinknxg_einvoice_hub.tests.bench_uae.run \
        --kwargs "{'resources': '/opt/pint-ae-resources-1.0.5'}"

``resources`` (optional) is a folder holding the unzipped official PINT AE resources as ``billing/``
and ``sb/``; with it, every outbound document is also checked against the official Schematron inside
the pipeline (``official_validation: required``). The UAE Compliance Profile's engine settings are
restored when the run ends.

The checks run the real pipeline (ingest -> normalise -> validate -> generate -> submit -> status)
against the built-in SANDBOX adapter. They create records in a dedicated tenant (code AETEST) and
leave them for inspection. Nothing leaves the server.
"""

import copy
import uuid as uuidlib

import frappe

from thinknxg_einvoice_hub.tests import uae_fixtures as F

TENANT = "UAE Test Tenant"
RESULTS = []


def check(name, condition, detail=""):
	RESULTS.append((name, bool(condition), detail))
	print(("PASS " if condition else "FAIL ") + name + (f"  [{detail}]" if detail and not condition else ""))


def _ensure(doctype, filters, values):
	name = frappe.db.get_value(doctype, filters)
	if name:
		doc = frappe.get_doc(doctype, name)
		doc.update(values)
		doc.save(ignore_permissions=True)
		return doc
	return frappe.get_doc({"doctype": doctype, **filters, **values}).insert(ignore_permissions=True)


def _profile(tenant, asp, party, complete=True):
	addr = party["address"]
	values = {"tenant": tenant, "country_code": "AE", "compliance_profile": "uae_pint_ae", "asp_connection": asp,
		"auto_submit": 1, "enabled": 1, "tax_id": party["tax_id"], "street": addr["street"], "city": addr["city"],
		"postal_code": addr.get("postal_code"), "subdivision": addr["subdivision"],
		"legal_registration_id": party.get("legal_registration_id") if complete else None,
		"legal_registration_type": party.get("legal_registration_type") if complete else None,
		"legal_registration_authority": party.get("legal_registration_authority") if complete else None}
	return _ensure("Company Integration Profile", {"tenant": tenant, "company_name": party["legal_name"]}, values)


def setup():
	tenant = _ensure("Integration Tenant", {"tenant_name": TENANT}, {"tenant_code": "AETEST"})
	asp = _ensure("ASP Connection", {"connection_name": "UAE Test Sandbox", "tenant": tenant.name},
		{"asp_provider": "sandbox", "environment": "Sandbox", "enabled": 1, "auth_type": "None"})
	seller = _profile(tenant.name, asp.name, F.SELLER)
	incomplete = _profile(tenant.name, asp.name, dict(F.SELLER, legal_name="ABC Trading LLC (no licence data)",
		tax_id="100000000100003"), complete=False)
	return tenant.name, seller.name, incomplete.name


def _outbound(tenant, profile, inv, number):
	from thinknxg_einvoice_hub.services import invoice_service

	inv = copy.deepcopy(inv)
	inv["document"]["invoice_number"] = number
	inv["supplier"] = {}  # the company profile supplies the seller, as for a real ERP
	name = invoice_service.ingest_outbound(tenant, profile, inv)
	invoice_service.process_transaction(name)
	return frappe.get_doc("Invoice Transaction", name)


def run(resources=None):
	from thinknxg_einvoice_hub.core import document_manager as dm

	RESULTS.clear()
	frappe.set_user("Administrator")
	cp = frappe.get_doc("Compliance Profile", "uae_pint_ae")
	saved = cp.engine_settings
	try:
		settings = {"official_validation": "off"}
		if resources:
			settings = {"schematron_dir": f"{resources}/billing", "selfbilling_schematron_dir": f"{resources}/sb",
				"official_validation": "required"}
		cp.engine_settings = frappe.as_json(settings)
		cp.save(ignore_permissions=True)
		tenant, seller, incomplete = setup()
		frappe.db.commit()
		frappe.clear_cache(doctype="Compliance Profile")
		run_id = uuidlib.uuid4().hex[:6].upper()
		issues = lambda t: [(m.severity, m.rule_id) for m in t.validation_messages if m.severity != "Info"]

		# 1 every fixture through the whole pipeline: no hub or official findings, sandbox delivery, UUID stored
		for i, (name, build) in enumerate(F.SCENARIOS.items(), 1):
			t = _outbound(tenant, seller, build(), f"AE-{run_id}-{i:02d}")
			check(f"{name}: Delivered with no validation findings",
				t.status == "Delivered" and issues(t) == [], f"{t.status} {t.last_error} {issues(t)}")
			check(f"{name}: BTAE-07 UUID stored", bool(t.document_uuid) and
				f"<cbc:UUID>{t.document_uuid}</cbc:UUID>" in (dm.get_payload(t.name, "Compliance Document") or ""))

		# 2 the company profile's trade licence data reaches the XML
		t = frappe.get_doc("Invoice Transaction", {"invoice_number": f"AE-{run_id}-01", "tenant": tenant})
		xml = dm.get_payload(t.name, "Compliance Document") or ""
		check("profile legal registration authority in the XML",
			'schemeAgencyName="Dubai Department of Economy and Tourism"' in xml)

		# 3 a profile without legal registration is stopped before submission, with the field to fix
		t = _outbound(tenant, incomplete, F.standard(), f"AE-{run_id}-90")
		fields = {m.field_path for m in t.validation_messages if m.rule_id == "EIH-AE-019"}
		check("incomplete profile: Validation Failed before submission",
			t.status == "Validation Failed" and not t.asp_reference, (t.status, issues(t)))
		check("incomplete profile: EIH-AE-019 names supplier.legal_registration_id",
			fields == {"supplier.legal_registration_id"}, fields)

		# 4 credit note without a reason is stopped (ibr-158-ae)
		cn = F.credit_note()
		cn["references"].pop("credit_reason_code")
		t = _outbound(tenant, seller, cn, f"AE-{run_id}-91")
		check("credit note without BTAE-03: Validation Failed with EIH-AE-060",
			t.status == "Validation Failed" and ("Error", "EIH-AE-060") in issues(t), (t.status, issues(t)))

		frappe.db.commit()
	finally:
		cp.reload()
		cp.engine_settings = saved
		cp.save(ignore_permissions=True)
		frappe.db.commit()
		frappe.clear_cache(doctype="Compliance Profile")
	failed = [r for r in RESULTS if not r[1]]
	print(f"\n{len(RESULTS) - len(failed)} passed, {len(failed)} failed")
	return {"passed": len(RESULTS) - len(failed), "failed": [r[0] for r in failed]}
