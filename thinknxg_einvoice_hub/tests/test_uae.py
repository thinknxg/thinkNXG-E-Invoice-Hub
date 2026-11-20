"""Framework-independent tests for the UAE PINT AE 1.0.5 engine.

Run from the app folder without a bench:
    python -m unittest thinknxg_einvoice_hub.tests.test_uae

Optional official check: set AE_PINT_RESOURCES to the unzipped official PINT AE 1.0.5
billing resources (and AE_PINT_SB_RESOURCES to the self-billing resources) and install
``saxonche``; TestOfficialSchematron then runs every fixture through the official
Schematron and requires zero errors and zero warnings. Set UBL21_XSD_DIR (folder with
maindoc/UBL-Invoice-2.1.xsd) and install ``xmlschema`` to also check the UBL 2.1 schema.
"""

import copy
import json
import os
import unittest
import xml.etree.ElementTree as ET

from thinknxg_einvoice_hub.canonical.normalizer import normalize
from thinknxg_einvoice_hub.compliance.registry import get_engine
from thinknxg_einvoice_hub.compliance.shared.xml import UBL_NS
from thinknxg_einvoice_hub.compliance.uae import codes
from thinknxg_einvoice_hub.tests import uae_fixtures as F

HERE = os.path.dirname(__file__)
GOLDEN = os.path.join(HERE, "golden", "uae")
REGEN = os.environ.get("REGENERATE_UAE_GOLDENS") == "1"


def prepared(inv, **settings):
	e = get_engine("uae_pint_ae", settings)
	return e, e.enrich(normalize(inv))


def errors(issues):
	return sorted({i["rule_id"] for i in issues if i["severity"] == "Error"})


def generated(inv, **settings):
	e, out = prepared(inv, **settings)
	issues = e.validate(out)
	assert not errors(issues), issues
	doc = e.generate_document(out)
	return e, out, doc, ET.fromstring(doc["content"].encode())


def text(root, path):
	return root.findtext(path, namespaces=UBL_NS)


def legacy_cases():
	"""The inputs of the v0.2.0 regression goldens (now completed with the data PINT AE requires)."""
	from thinknxg_einvoice_hub.tests import test_engine as T

	with open(os.path.join(HERE, "..", "..", "samples", "canonical_invoice.json"), encoding="utf-8") as f:
		sample = json.load(f)
	cases = {"sample": sample, "test_invoice": copy.deepcopy(T.INVOICE)}
	cn = copy.deepcopy(T.INVOICE)
	cn["document"].update(document_type="CREDIT_NOTE", invoice_number="CN-1")
	cn["references"] = {"original_invoice_number": "INV-1", "original_invoice_date": "2026-11-11",
		"credit_reason_code": "DL8.61.1.D"}
	cases["credit_note"] = cn
	usd = copy.deepcopy(T.INVOICE)
	usd["document"].update(currency="USD", exchange_rate="3.6725")
	cases["usd"] = usd
	mixed = copy.deepcopy(T.INVOICE)
	mixed["lines"].append({"item_name": "Export svc", "quantity": 1, "unit_price": 333.335, "tax_category": "ZERO_RATED",
		"tax_rate": 0})
	cases["mixed"] = mixed
	return cases


class TestGoldens(unittest.TestCase):
	"""UAE XML is pinned byte for byte. The goldens were regenerated deliberately for 0.3.1 (PINT AE 1.0.5
	layout, see CHANGELOG); any other change to them is a regression. Regenerate with
	REGENERATE_UAE_GOLDENS=1 only when the output is meant to change."""

	def check(self, name, inv):
		e, out = prepared(inv)
		content = e.generate_document(out)["content"]
		path = os.path.join(GOLDEN, f"{name}.xml")
		if REGEN:
			os.makedirs(os.path.dirname(path), exist_ok=True)
			with open(path, "w", encoding="utf-8") as f:
				f.write(content)
		with open(path, encoding="utf-8") as f:
			self.assertEqual(content, f.read(), name)

	def test_legacy_inputs(self):
		for name, inv in legacy_cases().items():
			with self.subTest(name):
				self.check(name, inv)

	def test_fixtures(self):
		for name, build in F.SCENARIOS.items():
			with self.subTest(name):
				self.check(os.path.join("fixtures", name), build())


class TestHubChecks(unittest.TestCase):
	def test_every_fixture_passes_hub_checks(self):
		for name, build in F.SCENARIOS.items():
			with self.subTest(name):
				e, out = prepared(build())
				self.assertEqual([i for i in e.validate(out) if i["severity"] != "Info"], [], name)

	def test_legacy_inputs_pass(self):
		for name, inv in legacy_cases().items():
			with self.subTest(name):
				e, out = prepared(inv)
				self.assertEqual(errors(e.validate(out)), [], name)

	def test_data_the_official_rules_need_is_reported_before_submission(self):
		"""Each case is data the official 1.0.5 Schematron rejects; the hub must name the canonical field."""
		cases = {
			"EIH-AE-019": lambda i: i["supplier"].pop("legal_registration_id"),
			"EIH-AE-020": lambda i: i["supplier"].update(legal_registration_type="CR"),
			"EIH-AE-021": lambda i: i["supplier"].pop("legal_registration_authority"),
			"EIH-AE-009": lambda i: i["payment"].pop("iban"),
			"EIH-AE-007": lambda i: i["document"].pop("due_date"),
			"EIH-AE-016": lambda i: i["customer"].update(tax_id="100234567800001"),
			"EIH-AE-013": lambda i: i["customer"]["address"].pop("subdivision"),
			"EIH-AE-014": lambda i: i["customer"]["address"].update(subdivision="ABU"),
			"EIH-AE-042": lambda i: i["lines"][0].update(tax_rate=10),
			"EIH-AE-036": lambda i: i["lines"][0].pop("commodity_code"),
			"EIH-AE-026": lambda i: i["document"].update(tax_point_date="2026-11-20"),
			"EIH-AE-062": lambda i: i["document"].update(transaction_type_flags="00010000"),
			"EIH-AE-064": lambda i: i["document"].update(transaction_type_flags="00000100"),
			"EIH-AE-024": lambda i: i["document"].update(tax_currency="USD"),
		}
		for rule, mutate in cases.items():
			with self.subTest(rule):
				inv = F.standard()
				mutate(inv)
				e, out = prepared(inv)
				self.assertIn(rule, errors(e.validate(out)))

	def test_credit_note_rules(self):
		inv = F.credit_note()
		inv["references"].pop("credit_reason_code")
		self.assertIn("EIH-AE-060", errors(prepared(inv)[0].validate(prepared(inv)[1])))
		inv["references"]["credit_reason_code"] = "DL8.61.1.Z"
		self.assertIn("EIH-AE-060", errors(prepared(inv)[0].validate(prepared(inv)[1])))
		vd = F.volume_discount_credit_note()   # VD: no preceding invoice needed (ibr-055-ae)
		self.assertEqual(errors(prepared(vd)[0].validate(prepared(vd)[1])), [])

	def test_category_rules(self):
		exempt = F.mixed()
		exempt["lines"][2].pop("exemption_reason_code")
		self.assertIn("EIH-AE-044", errors(prepared(exempt)[0].validate(prepared(exempt)[1])))
		rc = F.reverse_charge()
		rc["lines"][0].pop("rcm_goods_type")
		rc["lines"][0].pop("standard_item_id")
		rc["lines"][0]["tax_amount"] = 4500
		e, out = prepared(rc)
		self.assertTrue({"EIH-AE-043", "EIH-AE-047", "EIH-AE-048"} <= set(errors(e.validate(out))))
		only_exempt = F.standard()
		only_exempt["lines"] = [F.mixed()["lines"][2]]
		self.assertIn("EIH-AE-045", errors(prepared(only_exempt)[0].validate(prepared(only_exempt)[1])))
		commercial = F.out_of_scope()
		commercial["lines"].append(copy.deepcopy(F.SERVICE))
		self.assertIn("EIH-AE-045", errors(prepared(commercial)[0].validate(prepared(commercial)[1])))


class TestGenerator(unittest.TestCase):
	def test_mandatory_pint_ae_elements(self):
		_e, out, doc, root = generated(F.standard())
		self.assertEqual(text(root, "cbc:UUID"), out["document"]["uuid"])
		self.assertEqual(doc["document_uuid"], out["document"]["uuid"])
		self.assertEqual(text(root, "cac:PaymentMeans/cbc:PaymentMeansCode"), "30")
		self.assertEqual(text(root, "cac:TaxTotal/cbc:TaxIncludedIndicator"), "false")
		legal = root.find("cac:AccountingSupplierParty/cac:Party/cac:PartyLegalEntity/cbc:CompanyID", UBL_NS)
		self.assertEqual((legal.get("schemeAgencyID"), legal.get("schemeAgencyName")),
			("TL", "Dubai Department of Economy and Tourism"))
		line = root.find("cac:InvoiceLine", UBL_NS)
		self.assertEqual(text(line, "cac:Item/cbc:Description"), "Laptop computer, 14 inch, 16 GB")
		self.assertEqual(text(line, "cac:Item/cac:CommodityClassification/cbc:CommodityCode"), "G")
		self.assertEqual(text(line, "cac:Price/cbc:BaseQuantity"), "1")
		self.assertEqual(text(line, "cac:Price/cac:AllowanceCharge/cbc:BaseAmount"), "3500")
		self.assertEqual(text(line, "cac:ItemPriceExtension/cbc:Amount"), "7350.00")        # BTAE-10
		self.assertEqual(text(line, "cac:ItemPriceExtension/cac:TaxTotal/cbc:TaxAmount"), "350.00")  # BTAE-08
		service = root.findall("cac:InvoiceLine", UBL_NS)[1]
		self.assertEqual(text(service, "cac:Item/cbc:Description"), "Consulting")  # falls back to the item name

	def test_uuid_is_stable_and_erp_value_wins(self):
		a = prepared(F.standard())[1]["document"]["uuid"]
		self.assertEqual(a, prepared(F.standard())[1]["document"]["uuid"])
		self.assertNotEqual(a, prepared(F.standard() | {"document": dict(F.standard()["document"],
			invoice_number="OTHER")})[1]["document"]["uuid"])
		mine = F.standard()
		mine["document"]["uuid"] = "4b6000ca-0128-4bdc-99a6-406f2909247f"
		self.assertEqual(prepared(mine)[1]["document"]["uuid"], "4b6000ca-0128-4bdc-99a6-406f2909247f")

	def test_exempt_line_has_no_line_vat(self):
		_e, _o, _d, root = generated(F.mixed())
		exempt = root.findall("cac:InvoiceLine", UBL_NS)[2]
		self.assertEqual(text(exempt, "cac:Item/cac:ClassifiedTaxCategory/cbc:ID"), "E")
		self.assertIsNone(exempt.find("cac:Item/cac:ClassifiedTaxCategory/cbc:Percent", UBL_NS))
		self.assertEqual(text(exempt, "cac:Item/cac:ClassifiedTaxCategory/cbc:TaxExemptionReasonCode"), "DL8.46.2")
		self.assertIsNone(exempt.find("cac:ItemPriceExtension/cac:TaxTotal", UBL_NS))   # ibr-163-ae
		self.assertEqual(text(exempt, "cac:ItemPriceExtension/cbc:Amount"), "8000.00")

	def test_foreign_currency(self):
		_e, _o, _d, root = generated(F.foreign_currency())
		self.assertEqual(text(root, "cbc:TaxCurrencyCode"), "AED")
		self.assertEqual(text(root, "cac:TaxExchangeRate/cbc:SourceCurrencyCode"), "USD")
		self.assertEqual(text(root, "cac:TaxExchangeRate/cbc:TargetCurrencyCode"), "AED")
		self.assertEqual(text(root, "cac:TaxExchangeRate/cbc:CalculationRate"), "3.6725")
		aed = [t for t in root.findall("cac:TaxTotal", UBL_NS)
			if t.find("cbc:TaxAmount", UBL_NS).get("currencyID") == "AED"]
		self.assertEqual(len(aed), 1)
		# 2 x 950.50 = 1901.00 USD + 95.05 VAT = 1996.05 USD -> AED at 3.6725
		self.assertEqual(text(aed[0], "cbc:TaxAmount"), "349.07")
		ref = [r for r in root.findall("cac:AdditionalDocumentReference", UBL_NS)
			if text(r, "cbc:DocumentTypeCode") == codes.AED_TOTAL_REFERENCE]
		self.assertEqual(text(ref[0], "cbc:DocumentDescription"), "7330.49")
		line = root.find("cac:InvoiceLine", UBL_NS)
		self.assertEqual(line.find("cac:ItemPriceExtension/cbc:Amount", UBL_NS).get("currencyID"), "AED")

	def test_export_uses_the_predefined_endpoint(self):
		e, out, _d, root = generated(F.export())
		self.assertEqual(out["customer"]["tin"], codes.EXPORT_ENDPOINT)
		self.assertEqual(text(root, "cac:AccountingCustomerParty/cac:Party/cbc:EndpointID"), "9900000099")
		# an ERP-supplied buyer address always wins
		inv = F.export()
		inv["customer"]["tin"] = "9900000098"
		self.assertEqual(prepared(inv)[1]["customer"]["tin"], "9900000098")

	def test_reverse_charge_and_margin(self):
		_e, _o, _d, root = generated(F.reverse_charge())
		item = root.find("cac:InvoiceLine/cac:Item", UBL_NS)
		self.assertEqual(text(item, "cac:CommodityClassification/cbc:NatureCode"), "DL8.48.8.2")
		self.assertEqual(item.find("cac:StandardItemIdentification/cbc:ID", UBL_NS).get("schemeID"), "0160")
		self.assertEqual(text(root, "cac:InvoiceLine/cac:ItemPriceExtension/cac:TaxTotal/cbc:TaxAmount"), "0.00")
		self.assertEqual(text(root, "cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory/cbc:ID"), "AE")
		_e, _o, _d, root = generated(F.margin_scheme())
		self.assertEqual(text(root, "cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory/cbc:ID"), "N")
		self.assertEqual(text(root, "cac:TaxTotal/cbc:TaxAmount"), "0.00")

	def test_credit_notes(self):
		_e, _o, _d, root = generated(F.credit_note())
		self.assertEqual(text(root, "cbc:CreditNoteTypeCode"), "381")
		self.assertEqual(text(root, "cac:DiscrepancyResponse/cbc:ResponseCode"), "DL8.61.1.D")
		self.assertEqual(text(root, "cac:BillingReference/cac:InvoiceDocumentReference/cbc:ID"), "AE-INV-2026-0001")
		self.assertIsNone(root.find("cbc:TaxPointDate", UBL_NS))
		vd = F.volume_discount_credit_note()
		vd["references"]["original_invoice_number"] = "AE-INV-2026-0001"
		e, out = prepared(vd)
		self.assertIn("EIH-AE-061", [i["rule_id"] for i in e.validate(out)])          # warned, then left out
		root = ET.fromstring(e.generate_document(out)["content"].encode())
		self.assertIsNone(root.find("cac:BillingReference", UBL_NS))
		_e, _o, _d, root = generated(F.commercial_credit_note())
		self.assertEqual(text(root, "cbc:CreditNoteTypeCode"), "81")

	def test_type_codes(self):
		self.assertEqual(text(generated(F.out_of_scope())[3], "cbc:InvoiceTypeCode"), "480")
		_e, _o, _d, root = generated(F.self_billing())
		self.assertEqual(text(root, "cbc:InvoiceTypeCode"), "389")
		self.assertEqual(text(root, "cbc:CustomizationID"), "urn:peppol:pint:selfbilling-1@ae-1")
		self.assertEqual(text(generated(F.self_billing_credit_note())[3], "cbc:CreditNoteTypeCode"), "261")
		sb_commercial = F.out_of_scope()
		sb_commercial["document"]["document_type"] = "SELF_BILLING_INVOICE"
		self.assertEqual(text(generated(sb_commercial)[3], "cbc:InvoiceTypeCode"), "480")  # not 389 (UNCL1001 sb list)

	def test_tax_point_date_only_when_earlier(self):
		inv = F.standard()
		inv["document"]["tax_point_date"] = "2026-11-10"
		self.assertEqual(text(generated(inv)[3], "cbc:TaxPointDate"), "2026-11-10")
		inv["document"]["tax_point_date"] = "2026-11-15"   # same day as the issue date: redundant, left out
		self.assertIsNone(generated(inv)[3].find("cbc:TaxPointDate", UBL_NS))

	def test_summary_invoice_period(self):
		root = generated(F.summary())[3]
		self.assertEqual(text(root, "cac:InvoicePeriod/cbc:DescriptionCode"), "MTH")
		self.assertEqual(text(root, "cac:InvoicePeriod/cbc:StartDate"), "2026-10-01")

	def test_parse_round_trip(self):
		for name in ("standard", "mixed", "reverse_charge", "credit_note", "self_billing_credit_note", "summary"):
			with self.subTest(name):
				e, out, doc, _root = generated(F.SCENARIOS[name]())
				back = e.enrich(normalize(e.parse_document(doc["content"])))
				self.assertEqual(back["document"]["document_type"], out["document"]["document_type"])
				self.assertEqual(back["document"]["uuid"], out["document"]["uuid"])
				self.assertEqual(back["totals"], out["totals"])
				self.assertEqual(back["supplier"]["legal_registration_authority"],
					out["supplier"]["legal_registration_authority"])
				self.assertEqual(back["references"].get("credit_reason_code"), out["references"].get("credit_reason_code"))
				for a, b in zip(back["lines"], out["lines"]):
					for key in ("item_type", "exemption_reason_code", "rcm_goods_type", "standard_item_id"):
						self.assertEqual(a.get(key), b.get(key), key)
				self.assertEqual(errors(e.validate(back)), [])


class TestOfficialValidationHook(unittest.TestCase):
	def test_not_configured_is_a_warning_never_a_pass(self):
		e, out, doc, _ = generated(F.standard())
		issues = e.validate_document(doc, out)
		self.assertEqual([(i["severity"], i["rule_id"]) for i in issues], [("Warning", "EIH-AE-090")])

	def test_required_mode_blocks_when_rules_are_missing(self):
		e, out, doc, _ = generated(F.standard(), official_validation="required", schematron_dir="/nonexistent")
		self.assertEqual([(i["severity"], i["rule_id"]) for i in e.validate_document(doc, out)],
			[("Error", "EIH-AE-090")])

	def test_off(self):
		e, out, doc, _ = generated(F.standard(), official_validation="off")
		self.assertEqual(e.validate_document(doc, out), [])

	def test_country_profile_lists_the_official_codes(self):
		info = get_engine("uae_pint_ae").get_country_profile()
		self.assertEqual(info["spec_version"], "1.0.5")
		self.assertIn("DL8.61.1.A", info["credit_reason_codes"])
		self.assertEqual(info["predefined_endpoints"]["export"], "9900000099")


@unittest.skipUnless(os.environ.get("AE_PINT_RESOURCES"), "set AE_PINT_RESOURCES to the official PINT AE billing resources")
class TestOfficialSchematron(unittest.TestCase):
	def settings(self):
		return {"schematron_dir": os.environ["AE_PINT_RESOURCES"],
			"selfbilling_schematron_dir": os.environ.get("AE_PINT_SB_RESOURCES"), "official_validation": "required"}

	def test_all_fixtures_pass_official_rules(self):
		for name, build in F.SCENARIOS.items():
			if "self_billing" in name and not os.environ.get("AE_PINT_SB_RESOURCES"):
				continue
			with self.subTest(name):
				e, inv, doc, _ = generated(build(), **self.settings())
				self.assertEqual(e.validate_document(doc, inv), [], name)

	def test_legacy_inputs_pass_official_rules(self):
		for name, inv in legacy_cases().items():
			with self.subTest(name):
				e, out, doc, _ = generated(inv, **self.settings())
				self.assertEqual(e.validate_document(doc, out), [], name)

	def test_official_rules_catch_what_the_hub_lets_through(self):
		"""The hub does not check passport issuing countries against ISO 3166 beyond their shape;
		the official rules do (ibr-010-ae)."""
		inv = F.export()
		inv["customer"]["legal_registration_authority"] = "ZZ"
		e, out, doc, _ = generated(inv, **self.settings())
		self.assertIn("ibr-010-ae", errors(e.validate_document(doc, out)))


@unittest.skipUnless(os.environ.get("UBL21_XSD_DIR"), "set UBL21_XSD_DIR to the UBL 2.1 xsd folder")
class TestUBLSchema(unittest.TestCase):
	def test_fixtures_are_schema_valid(self):
		import xmlschema

		locations = [("urn:un:unece:uncefact:documentation:2", os.environ["CCTS_XSD"])] if os.environ.get("CCTS_XSD") else None
		schemas = {k: xmlschema.XMLSchema(os.path.join(os.environ["UBL21_XSD_DIR"], "maindoc", f"UBL-{k}-2.1.xsd"),
			validation="lax", locations=locations) for k in ("Invoice", "CreditNote")}
		for name, build in F.SCENARIOS.items():
			with self.subTest(name):
				_e, _o, doc, root = generated(build())
				kind = "CreditNote" if root.tag.endswith("CreditNote") else "Invoice"
				self.assertEqual(list(schemas[kind].iter_errors(doc["content"])), [], name)


if __name__ == "__main__":
	unittest.main()
