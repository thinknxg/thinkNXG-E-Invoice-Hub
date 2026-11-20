"""Bench integration checks for Oman Fawtara (needs a site with the app installed).

    bench --site <site> execute thinknxg_einvoice_hub.tests.bench_oman.run \
        --kwargs "{'resources': '/opt/pint-om-resources-1.0.1'}"

``resources`` (optional) is a folder holding the unzipped official PINT OM resources as
``billing/`` and ``sb/``; with it, every outbound document is also checked against the official
Schematron inside the pipeline (``official_validation: required``).

The checks run the real pipeline (ingest -> normalise -> validate -> generate -> submit -> status
-> ERP sync) against the MOCK Oman provider in ``mock_oman_provider.py``. They create records in a
dedicated tenant (code OMTEST) and leave them for inspection. Nothing leaves the server.
"""

import copy
import json
import uuid as uuidlib

import frappe

from thinknxg_einvoice_hub.tests import mock_oman_provider as mock
from thinknxg_einvoice_hub.tests import oman_fixtures as F

TENANT = "Oman Test Tenant"
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


def setup(resources=None):
	from thinknxg_einvoice_hub.asp_connectors import adapter_registry

	adapter_registry.BUILTIN_ADAPTERS["mock_oman"] = "thinknxg_einvoice_hub.tests.mock_oman_provider.MockOmanProvider"
	tenant = _ensure("Integration Tenant", {"tenant_name": TENANT}, {"tenant_code": "OMTEST"})
	_ensure("ASP Provider", {"provider_code": "mock_oman"}, {"provider_name": "MOCK Oman provider (tests only)",
		"status": "Planned", "adapter_class": adapter_registry.BUILTIN_ADAPTERS["mock_oman"]})
	asp = _ensure("ASP Connection", {"connection_name": "Mock Oman ASP", "tenant": tenant.name},
		{"asp_provider": "mock_oman", "environment": "Sandbox", "enabled": 1, "auth_type": "None"})
	settings = {"official_validation": "off"}
	if resources:
		settings = {"schematron_dir": f"{resources}/billing", "selfbilling_schematron_dir": f"{resources}/sb",
			"official_validation": "required"}
	cp = frappe.get_doc("Compliance Profile", "om_pint_om")
	cp.engine_settings = json.dumps(settings)
	cp.save(ignore_permissions=True)
	seller, buyer = F.SELLER, F.BUYER
	common = {"tenant": tenant.name, "country_code": "OM", "compliance_profile": "om_pint_om",
		"asp_connection": asp.name, "auto_submit": 1, "enabled": 1}
	sp = _ensure("Company Integration Profile", {"company_name": seller["legal_name"], "tenant": tenant.name}, {
		**common, "tax_id": seller["tax_id"], "legal_registration_id": "1234567", "legal_registration_type": "CR",
		"street": seller["address"]["street"], "additional_street": seller["address"]["additional_street"],
		"address_line": seller["address"]["address_line"], "city": "Muscat", "postal_code": "112", "subdivision": "MO",
		"contact_name": "Accounts", "contact_phone": seller["contact"]["phone"]})
	bp = _ensure("Company Integration Profile", {"company_name": buyer["legal_name"], "tenant": tenant.name}, {
		**common, "tax_id": buyer["tax_id"], "street": "Industrial Area", "additional_street": "Plot 14",
		"address_line": "P.O. Box 77", "city": "Sohar", "postal_code": "311", "subdivision": "SHRFZ",
		"contact_phone": "+968 2600 0000"})
	frappe.db.commit()
	frappe.clear_cache(doctype="Compliance Profile")
	return tenant.name, asp.name, sp.name, bp.name


def _outbound(tenant, profile, inv, number):
	from thinknxg_einvoice_hub.services import invoice_service

	inv = copy.deepcopy(inv)
	inv["document"]["invoice_number"] = number
	inv["supplier"] = {}  # the company profile supplies the seller, as for a real ERP
	name = invoice_service.ingest_outbound(tenant, profile, inv)
	invoice_service.process_transaction(name)
	return frappe.get_doc("Invoice Transaction", name)


def run(resources=None):
	from thinknxg_einvoice_hub.compliance.oman import identifiers
	from thinknxg_einvoice_hub.core import document_manager as dm
	from thinknxg_einvoice_hub.services import invoice_service, monitoring

	RESULTS.clear()
	frappe.set_user("Administrator")
	tenant, asp, seller, buyer = setup(resources)
	run_id = uuidlib.uuid4().hex[:6].upper()
	errors = lambda t: [m.rule_id for m in t.validation_messages if m.severity == "Error"]

	# 1 standard B2B invoice: validated, generated, accepted, reported (TDD MLS AP), delivered (invoice MLS AP)
	t = _outbound(tenant, seller, F.standard(), f"OM-{run_id}-1")
	check("standard: overall Delivered", t.status == "Delivered", f"{t.status} {t.last_error} {errors(t)}")
	check("standard: four outcomes", (t.validation_status, t.asp_submission_status, t.fta_status, t.delivery_status)
		== ("Passed", "Accepted", "Reported", "Delivered"),
		(t.validation_status, t.asp_submission_status, t.fta_status, t.delivery_status))
	check("standard: country OM, UUID v5", t.country_code == "OM" and identifiers.is_uuid_v5(t.document_uuid), t.document_uuid)
	stored = mock.STORE.get(t.asp_reference) or {}
	check("standard: provider recomputed the same UUID", stored.get("uuid") == t.document_uuid)
	check("standard: no validation errors", not errors(t), errors(t))
	original = t

	# 2 credit note: the ERP sends only the original number; the hub adds the original UUID (BTOM-031)
	cn = F.credit_note(None)
	cn["references"].pop("original_invoice_uuid")
	cn["references"]["original_invoice_number"] = original.invoice_number
	t = _outbound(tenant, seller, cn, f"OM-{run_id}-CN")
	check("credit note: Delivered", t.status == "Delivered", f"{t.status} {errors(t)} {t.last_error}")
	check("credit note: original UUID from hub records",
		original.document_uuid in (mock.STORE.get(t.asp_reference) or {}).get("xml", ""))

	# 3 B2C: no Peppol delivery; a confirmed tax report completes the document
	t = _outbound(tenant, seller, F.b2c(), f"POS-{run_id}-1")
	check("B2C: overall Reported", t.status == "Reported", f"{t.status} {errors(t)} {t.last_error}")
	check("B2C: delivery not expected / not applicable",
		(t.peppol_delivery_expected, t.delivery_status, t.fta_status) == (0, "Not Applicable", "Reported"),
		(t.peppol_delivery_expected, t.delivery_status, t.fta_status))

	# 4 TDD rejected by the Tax Authority's access point
	t = _outbound(tenant, seller, F.standard(), f"OM-{run_id}-TDDRE")
	check("TDD rejected: overall Rejected, reporting Rejected", (t.status, t.fta_status) == ("Rejected", "Rejected"),
		(t.status, t.fta_status))

	# 5 buyer's provider rejects the invoice
	t = _outbound(tenant, seller, F.standard(), f"OM-{run_id}-C3RE")
	check("C3 rejected: delivery Failed", t.delivery_status == "Failed" and t.fta_status == "Reported",
		(t.status, t.delivery_status, t.fta_status))

	# 6 MLS arrives later: Submitted / Pending, then a status poll completes it
	t = _outbound(tenant, seller, F.standard(), f"OM-{run_id}-LATE")
	check("late MLS: Submitted with reporting Pending", (t.status, t.fta_status) == ("Submitted", "Pending"),
		(t.status, t.fta_status))
	invoice_service.refresh_asp_status(t.name)
	t.reload()
	check("late MLS: status poll -> Delivered", (t.status, t.fta_status, t.delivery_status) ==
		("Delivered", "Reported", "Delivered"), (t.status, t.fta_status, t.delivery_status))

	# 7 temporary provider failure -> Retrying -> success on the next run
	t = _outbound(tenant, seller, F.standard(), f"OM-{run_id}-TIMEOUT")
	check("retry: first attempt Retrying", t.status == "Retrying", t.status)
	invoice_service.process_transaction(t.name)
	t.reload()
	check("retry: second attempt Delivered", t.status == "Delivered", f"{t.status} {t.last_error}")

	# 8 duplicate submission of the same invoice number
	t = _outbound(tenant, seller, F.standard(), original.invoice_number)
	check("duplicate detected", t.status == "Duplicate" and t.duplicate_of == original.name, (t.status, t.duplicate_of))

	# 9 hub validation failure
	bad = F.standard()
	bad["customer"]["tax_id"] = "OM123"
	t = _outbound(tenant, seller, bad, f"OM-{run_id}-BAD")
	check("validation failure: EIH-OM-016", t.status == "Validation Failed" and "EIH-OM-016" in errors(t), errors(t))

	# 10 official Schematron inside the pipeline (HS code with the right format but not in Oman's list)
	if resources:
		bad = F.standard()
		bad["lines"][0]["commodity_code"] = "999999999999"
		t = _outbound(tenant, seller, bad, f"OM-{run_id}-HS")
		check("official Schematron in pipeline: CL-08-OM-HS", t.status == "Validation Failed" and "CL-08-OM-HS" in errors(t),
			(t.status, errors(t)))

	# 11 inbound: a PINT OM invoice for the buyer company arrives from the provider
	xml = (mock.STORE.get(original.asp_reference) or {}).get("xml")
	name = invoice_service.ingest_inbound(tenant, asp, xml, f"IN-{run_id}")
	invoice_service.process_transaction(name)
	t = frappe.get_doc("Invoice Transaction", name)
	inv = dm.get_payload(name, "Canonical")
	check("inbound: matched to buyer company, Oman engine", t.company_profile == buyer and t.country_code == "OM",
		(t.company_profile, t.country_code, t.status, t.last_error))
	check("inbound: canonical carries UUID and lines", t.document_uuid == original.document_uuid and len(inv["lines"]) == 2,
		(t.document_uuid, t.status))
	check("inbound: validated", t.validation_status == "Passed", (t.status, errors(t)))

	# 11b multi-country tenant: a UAE document arriving in the same tenant is parsed by the UAE engine
	import os

	_ensure("Company Integration Profile", {"company_name": "XYZ LLC (AE test buyer)", "tenant": tenant}, {
		"tenant": tenant, "country_code": "AE", "compliance_profile": "uae_pint_ae", "tax_id": "100234567800003",
		"asp_connection": asp, "enabled": 1})
	frappe.db.commit()
	with open(os.path.join(os.path.dirname(__file__), "golden", "uae", "test_invoice.xml"), encoding="utf-8") as f:
		uae_xml = f.read()
	name = invoice_service.ingest_inbound(tenant, asp, uae_xml, f"IN-AE-{run_id}")
	invoice_service.process_transaction(name)
	t = frappe.get_doc("Invoice Transaction", name)
	uae_uuid = uae_xml.split("<cbc:UUID>", 1)[1].split("<", 1)[0]  # BTAE-07 since 0.3.1
	check("multi-country inbound: UAE document -> UAE engine", t.country_code == "AE" and t.document_uuid == uae_uuid,
		(t.country_code, t.company_profile, t.status, t.document_uuid, t.last_error))
	name = invoice_service.ingest_inbound(tenant, asp, xml, f"IN2-{run_id}")
	invoice_service.process_transaction(name)
	t = frappe.get_doc("Invoice Transaction", name)
	check("multi-country inbound: Oman document -> Oman engine", t.country_code == "OM" and t.company_profile == buyer,
		(t.country_code, t.company_profile, t.status, t.last_error))

	# 12 dashboard figures come from real records, filtered by country
	d = monitoring.get_dashboard(country="OM", tenant=tenant)
	expected = frappe.db.count("Invoice Transaction", {"tenant": tenant, "country_code": "OM"})
	check("dashboard: Oman count", d["invoices"]["received"] == expected and d["by_country"].get("OM") == expected,
		(d["invoices"]["received"], expected))

	# 13 Oman API
	from thinknxg_einvoice_hub.api import oman as api

	res = api.validate_invoice(invoice=json.dumps(dict(F.standard(), supplier={})), company=seller, tenant=tenant)
	check("API validate_invoice: PASSED", res["validation_status"] == "PASSED", res.get("errors"))
	res = api.generate_document(invoice=json.dumps(dict(F.b2c(), supplier={})), company=seller, tenant=tenant)
	check("API generate_document: XML, UUID, QR", res["success"] and res["document"].startswith("<?xml")
		and identifiers.is_uuid_v5(res["document_uuid"]) and res["qr_base64"], res.get("errors"))
	try:
		uae = frappe.db.get_value("Company Integration Profile", {"compliance_profile": "uae_pint_ae"}, ["name", "tenant"])
		api.validate_invoice(invoice=json.dumps(F.standard()), company=uae[0], tenant=uae[1]) if uae else None
		check("API refuses a UAE company", not uae, "no exception raised")
	except frappe.ValidationError:
		check("API refuses a UAE company", True)

	# 14 UAE still works end to end on the same site
	# (a UAE profile with complete legal registration data, e.g. the one bench_uae.py creates)
	uae_profile = frappe.db.get_value("Company Integration Profile", {"compliance_profile": "uae_pint_ae",
		"asp_connection": ["is", "set"], "enabled": 1, "tenant": ["!=", tenant],
		"legal_registration_authority": ["is", "set"]}, ["name", "tenant"], as_dict=True, order_by="creation asc")
	if uae_profile:
		from thinknxg_einvoice_hub.tests import test_engine as T

		t = _outbound(uae_profile.tenant, uae_profile.name, T.INVOICE, f"AE-{run_id}-1")
		check("UAE regression: sandbox flow Delivered, country AE, BTAE-07 UUID set",
			(t.status, t.country_code, bool(t.document_uuid)) == ("Delivered", "AE", True),
			(t.status, t.country_code, t.last_error))

	frappe.db.commit()
	failed = [r for r in RESULTS if not r[1]]
	print(f"\n{len(RESULTS) - len(failed)} passed, {len(failed)} failed")
	return {"passed": len(RESULTS) - len(failed), "failed": [r[0] for r in failed]}
