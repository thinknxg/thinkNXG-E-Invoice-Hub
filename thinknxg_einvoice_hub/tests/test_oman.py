"""Framework-independent tests for the Oman Fawtara (PINT OM) engine (UAE tests: test_uae.py).

Run from the app folder without a bench:
    python -m unittest thinknxg_einvoice_hub.tests.test_oman

Optional official check: set OM_PINT_RESOURCES (and OM_PINT_SB_RESOURCES) to the unzipped official
PINT OM 1.0.1 resources and install ``saxonche``; the TestOfficialSchematron cases then run every
fixture through the official Schematron and require zero errors and zero warnings.
"""

import os
import unittest
import xml.etree.ElementTree as ET
from decimal import Decimal

from thinknxg_einvoice_hub.canonical.normalizer import normalize
from thinknxg_einvoice_hub.compliance.oman import constants as C
from thinknxg_einvoice_hub.compliance.oman import identifiers, qr, status_mapper, transaction_types
from thinknxg_einvoice_hub.compliance.oman.tax_rules import TaxRules
from thinknxg_einvoice_hub.compliance.registry import get_engine
from thinknxg_einvoice_hub.compliance.shared.xml import UBL_NS
from thinknxg_einvoice_hub.erp_connectors.erpnext.connector import ERPNextConnector
from thinknxg_einvoice_hub.exceptions import PermanentError
from thinknxg_einvoice_hub.tests import oman_fixtures as F
from thinknxg_einvoice_hub.tests.mock_oman_provider import recompute_uuid



def engine(**settings):
	return get_engine("om_pint_om", settings)


def prepared(inv, **settings):
	e = engine(**settings)
	return e, e.normalize_invoice(inv)


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


class TestIdentifiers(unittest.TestCase):
	def test_seller_uuid_matches_official_example(self):
		# OM SRA 1.0.3 Appendix D
		self.assertEqual(identifiers.seller_uuid("01", "INVOICE-01", "بائع", "OM1234567891", "2026-05-13", "18:31:00",
			"302.340", "14.520"), "454cb7ea-f1f7-5b69-9e0b-756f002efa52")

	def test_invoice_uuid_follows_published_method(self):
		# OM SRA 1.0.3 section 10.2.3 input; output cross-checked with phax/peppol-om (the printed value is a typo)
		self.assertEqual(identifiers.invoice_uuid_input(" 0248\t", "5060012349998", "380", "33445566\r\n", "2026-01-13",
			"100.00", "105.00"), "0248 5060012349998 380 33445566 2026-01-13 100.00 105.00")
		self.assertEqual(identifiers.invoice_uuid("0248", "5060012349998", "380", "33445566", "2026-01-13", "100.00",
			"105.00"), "7b95376b-e63c-50e0-a0e9-62f2092288a6")
		self.assertTrue(identifiers.invoice_uuid_input("0248", "1", "380", "2", "2026-01-13", "1.00", "1.05", " 1032.210 ")
			.endswith(" 1032.210"))

	def test_vatin_and_participant(self):
		self.assertTrue(identifiers.is_vatin("OM1100003554"))
		self.assertFalse(identifiers.is_vatin("OM11000035"))
		self.assertEqual(identifiers.clean_vatin(" om 1100-003554"), "OM1100003554")
		self.assertEqual(identifiers.participant_id("OM1100003554"), "0248:OM1100003554")

	def test_qr_tlv_matches_official_example(self):
		pairs = qr.fields("INVOICE-01", "بائع", "OM1234567891", "2026-05-13", "18:31:00", "302.340", "14.520")
		raw = b"".join(qr.tlv(t, v) for t, v in pairs).hex()
		# per-field hex from the OM SRA Appendix D.2 table
		self.assertEqual(raw, "0103312e3102023031030a494e564f4943452d30310408d8a8d8a7d8a6d8b9050c4f4d31323334353637383931"
			"060a323032362d30352d3133070831383a33313a303008073330322e333430090631342e353230"
			"0a2434353463623765612d663166372d356236392d396530622d373536663030326566613532")
		self.assertEqual(qr.decode(qr.encode(pairs))[-1], (10, "454cb7ea-f1f7-5b69-9e0b-756f002efa52"))
		pm = qr.fields("INVOICE-01", "بائع", "OM1234567892", "2026-05-13", "18:30:00", "1032.210", profit_margin=True)
		self.assertEqual([t for t, _ in pm], list(range(1, 10)))
		self.assertEqual(pm[1], (2, "02"))
		with self.assertRaises(PermanentError):
			qr.encode([(1, "x" * 200), (2, "y" * 200), (3, "z" * 200)])


class TestCodeLists(unittest.TestCase):
	def test_transaction_types(self):
		flags = transaction_types.build(["FULL_TAX_INVOICE", "EXPORT"])
		self.assertEqual(flags, "10000010000000000000")
		self.assertEqual(transaction_types.names(flags), ["FULL_TAX_INVOICE", "EXPORT"])
		self.assertEqual(transaction_types.build(["DEEMED_SUPPLY"]), "00000001000000000000")  # OM SRA 10.3.1
		self.assertEqual(transaction_types.conflicts(transaction_types.build(["SELF_BILLED", "THIRD_PARTY"])),
			[("SELF_BILLED", "THIRD_PARTY")])
		self.assertEqual(transaction_types.derive({"document": {"document_type": "SELF_BILLING_INVOICE"}}),
			"10100000000000000000")

	def test_tax_rules(self):
		rules = TaxRules()
		self.assertEqual(rules.standard_rate("2026-01-01"), Decimal("5"))
		self.assertIsNone(rules.standard_rate("2020-01-01"))
		self.assertEqual(errors(rules.check("STANDARD", 5, 5, None, "x.tax_category", "2026-01-01")), [])
		self.assertEqual(errors(rules.check("STANDARD", 10, 10, None, "x.tax_category", "2026-01-01")), ["EIH-OM-042"])
		self.assertEqual(errors(rules.check("EXEMPT", 0, 0, None, "x.tax_category")), ["EIH-OM-045"])
		self.assertEqual(errors(rules.check("EXEMPT", 0, 0, "VATZR-OM-01", "x.tax_category")), ["EIH-OM-046"])
		self.assertEqual(errors(rules.check("ZERO_RATED", 0, 0, "VATZR-OM-10", "x.tax_category")), [])
		self.assertEqual(errors(rules.check("OUT_OF_SCOPE", 0, 0, "VATEX-OM-01", "x.tax_category")), ["EIH-OM-047"])
		self.assertEqual(errors(rules.check("REVERSE_CHARGE", 5, 0, None, "x.tax_category")), ["EIH-OM-040"])

	def test_rate_schedule_is_configurable(self):
		rules = TaxRules({"standard_rate_schedule": [("2021-04-16", "5"), ("2030-01-01", "7")]})
		self.assertEqual(rules.standard_rate("2030-06-01"), Decimal("7"))
		self.assertEqual(rules.standard_rate("2029-12-31"), Decimal("5"))

	def test_rest_engine_maps_mls_codes(self):
		from thinknxg_einvoice_hub.services.asp_rest_engine import ASPRestEngine

		cfg = {"response_mappings": [{"path": "peppol.mls", "target": "invoice_mls_code"},
			{"path": "tax.mls", "target": "tdd_mls_code"}, {"path": "id", "target": "asp_document_id"}]}
		mapped = ASPRestEngine().map_response(cfg, {"data": {"id": 7, "peppol": {"mls": "AP"}, "tax": {"mls": "RE"}}})
		self.assertEqual((mapped["invoice_mls_code"], mapped["tdd_mls_code"]), ("AP", "RE"))
		out = engine().parse_provider_response({"status": "ACCEPTED", **mapped})
		self.assertEqual((out["delivery_status"], out["fta_status"]), ("DELIVERED", "REJECTED"))

	def test_status_mapper(self):
		out = status_mapper.apply({"status": "ACCEPTED", "invoice_mls_code": "AP", "tdd_mls_code": "RE"})
		self.assertEqual((out["delivery_status"], out["fta_status"]), ("DELIVERED", "REJECTED"))
		self.assertNotIn("fta_status", status_mapper.apply({"status": "ACCEPTED"}))
		self.assertEqual(engine().map_transaction_status("AB"), "DELIVERED")
		self.assertEqual(engine().map_transaction_status("accepted"), "ACCEPTED")


class TestMapping(unittest.TestCase):
	def test_registry_has_both_countries(self):
		self.assertEqual(get_engine("uae_pint_ae").country_code, "AE")
		self.assertEqual(engine().country_code, "OM")
		profile = engine().get_country_profile()
		self.assertIn("SIMPLIFIED_TAX_INVOICE", profile["transaction_types"])
		self.assertEqual(profile["settings"]["uuid_namespace"], C.UUID_NAMESPACE)

	def test_normalizer_uses_baisa(self):
		inv = normalize(F.standard())
		self.assertEqual(inv["lines"][0]["net_amount"], 700.5)
		self.assertEqual(inv["lines"][1]["tax_amount"], 1.852)  # 37.035 x 5% = 1.85175 -> 3 decimals
		self.assertEqual(inv["totals"]["tax_total"], 36.877)

	def test_supplier_buyer_and_header(self):
		_, inv, doc, root = generated(F.standard())
		self.assertEqual(text(root, "cbc:CustomizationID"), C.CUSTOMIZATION_ID)
		self.assertEqual(text(root, "cbc:IssueTime"), "10:30:00")
		self.assertEqual(root.find("cbc:InvoiceTypeCode", UBL_NS).get("name"), "10000000000000000000")
		sup = root.find("cac:AccountingSupplierParty/cac:Party", UBL_NS)
		self.assertEqual(sup.find("cbc:EndpointID", UBL_NS).get("schemeID"), "0248")
		self.assertEqual(text(sup, "cbc:EndpointID"), "OM1100003554")
		self.assertEqual(sup.find("cac:PartyIdentification/cbc:ID", UBL_NS).get("schemeName"), "CR")
		self.assertEqual(text(sup, "cac:PostalAddress/cbc:CountrySubentityCode"), "MO")
		self.assertEqual(text(sup, "cac:PostalAddress/cac:AddressLine/cbc:Line"), "P.O. Box 192")
		self.assertEqual(text(sup, "cac:Contact/cbc:Telephone"), "+968 2400 0000")
		self.assertEqual(text(root, "cac:AccountingCustomerParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID"), "OM1100009876")

	def test_lines_and_decimals(self):
		_, _, _, root = generated(F.standard())
		line = root.findall("cac:InvoiceLine", UBL_NS)[1]
		self.assertEqual(text(line, "cbc:LineExtensionAmount"), "37.035")
		self.assertEqual(text(line, "cac:ItemPriceExtension/cac:TaxTotal/cbc:TaxAmount"), "1.852")
		self.assertEqual(text(line, "cac:ItemPriceExtension/cbc:Amount"), "38.887")
		item = line.find("cac:Item", UBL_NS)
		self.assertEqual(text(item, "cac:ItemSpecificationDocumentReference/cbc:DocumentTypeCode"), "S")
		self.assertEqual(text(item, "cac:ItemSpecificationDocumentReference/cbc:ID"), "81000000")
		self.assertEqual(text(item, "cac:AdditionalItemIdentification/cbc:ID"), "620101")
		goods = root.find("cac:InvoiceLine/cac:Item", UBL_NS)
		self.assertEqual(goods.find("cac:CommodityClassification/cbc:ItemClassificationCode", UBL_NS).get("listID"), "HS")
		lmt = root.find("cac:LegalMonetaryTotal", UBL_NS)
		self.assertEqual(text(lmt, "cbc:LineExtensionAmount"), "737.54")  # 700.500 + 37.035, rounded once
		self.assertEqual(text(root, "cac:TaxTotal/cbc:TaxAmount"), "36.88")
		self.assertEqual(text(lmt, "cbc:TaxInclusiveAmount"), "774.42")

	def test_invoice_uuid_is_what_the_provider_recomputes(self):
		for name, build in F.SCENARIOS.items():
			with self.subTest(name):
				_, _, doc, root = generated(build())
				self.assertTrue(identifiers.is_uuid_v5(doc["document_uuid"]))
				self.assertEqual(text(root, "cbc:UUID"), doc["document_uuid"])
				self.assertEqual(recompute_uuid(doc["content"]), doc["document_uuid"])

	def test_uuid_is_stable_and_content_sensitive(self):
		a = generated(F.standard())[2]["document_uuid"]
		self.assertEqual(a, generated(F.standard())[2]["document_uuid"])
		changed = F.standard()
		changed["lines"][0]["quantity"] = 3
		self.assertNotEqual(a, generated(changed)[2]["document_uuid"])

	def test_credit_note(self):
		original = generated(F.standard())[2]["document_uuid"]
		_, _, doc, root = generated(F.credit_note(original))
		self.assertEqual(root.tag, "{urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2}CreditNote")
		ref = root.find("cac:BillingReference/cac:InvoiceDocumentReference", UBL_NS)
		self.assertEqual(text(ref, "cbc:UUID"), original)
		self.assertEqual(text(ref, "cbc:DocumentStatusCode"), "CAN")
		self.assertEqual(text(root, "cbc:CreditNoteTypeCode"), "381")
		self.assertIsNotNone(root.find("cac:CreditNoteLine/cbc:CreditedQuantity", UBL_NS))

	def test_zero_rated_and_exempt_categories(self):
		_, _, _, root = generated(F.zero_rated())
		cat = root.find("cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory", UBL_NS)
		self.assertEqual((text(cat, "cbc:ID"), text(cat, "cbc:Percent"), text(cat, "cbc:TaxExemptionReasonCode")),
			("Z", "0", "VATZR-OM-01"))
		_, _, _, root = generated(F.exempt())
		cat = root.find("cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory", UBL_NS)
		self.assertEqual((text(cat, "cbc:ID"), text(cat, "cbc:Percent")), ("E", None))  # no rate for E (IBR-067-OM)

	def test_foreign_currency_layout(self):
		_, _, _, root = generated(F.foreign_currency())
		self.assertEqual(text(root, "cbc:TaxCurrencyCode"), "OMR")
		self.assertEqual(text(root, "cac:TaxExchangeRate/cbc:CalculationRate"), "0.3845")
		usd, omr = root.findall("cac:TaxTotal", UBL_NS)
		self.assertEqual(usd.find("cbc:TaxAmount", UBL_NS).get("currencyID"), "USD")
		self.assertEqual(usd.findall("cac:TaxSubtotal", UBL_NS), [])
		self.assertEqual(omr.find("cbc:TaxAmount", UBL_NS).get("currencyID"), "OMR")
		self.assertEqual(text(omr, "cac:TaxSubtotal/cac:TaxCategory/cbc:ID"), "S")
		self.assertEqual(text(omr, "cbc:TaxAmount"), "11.54")  # 30.00 USD x 0.3845

	def test_b2c_uses_substitute_buyer_and_seller_uuid(self):
		e, inv, doc, root = generated(F.b2c())
		self.assertEqual(text(root, "cac:AccountingCustomerParty/cac:Party/cbc:EndpointID"), C.B2C_PARTICIPANT)
		self.assertEqual(text(root, "cac:AccountingCustomerParty/cac:Party/cac:PartyLegalEntity/cbc:RegistrationName"),
			"General customer")
		self.assertEqual(root.find("cbc:InvoiceTypeCode", UBL_NS).get("name"), "01000000000000000000")
		seller_uuid = text(root, "cac:AccountingSupplierParty/cbc:AdditionalAccountID")
		self.assertTrue(identifiers.is_uuid_v5(seller_uuid))
		fields = dict(qr.decode(inv["extensions"]["om"]["qr_base64"]))
		self.assertEqual((fields[2], fields[3], fields[10]), ("01", "POS-2026-000981", seller_uuid))
		self.assertEqual(e.qr_payload(inv), inv["extensions"]["om"]["qr_base64"])

	def test_export_uses_substitute_participant(self):
		_, _, _, root = generated(F.export())
		self.assertEqual(text(root, "cac:AccountingCustomerParty/cac:Party/cbc:EndpointID"), "997770000097")
		self.assertEqual(text(root, "cac:Delivery/cac:DeliveryLocation/cac:Address/cac:Country/cbc:IdentificationCode"), "IN")

	def test_self_billing_and_allowances(self):
		_, _, _, root = generated(F.self_billing())
		self.assertEqual(text(root, "cbc:CustomizationID"), C.SELFBILLING_CUSTOMIZATION_ID)
		self.assertEqual(text(root, "cbc:InvoiceTypeCode"), "389")
		_, _, _, root = generated(F.allowance_charge())
		lmt = root.find("cac:LegalMonetaryTotal", UBL_NS)
		self.assertEqual((text(lmt, "cbc:AllowanceTotalAmount"), text(lmt, "cbc:ChargeTotalAmount")), ("10.50", "4.25"))
		# 36.877 line VAT + 0.2125 charge VAT - 0.525 allowance VAT = 36.5645 -> 36.56 (ALIGNED-IBRP-S-09-OM)
		self.assertEqual(text(root, "cac:TaxTotal/cbc:TaxAmount"), "36.56")

	def test_parse_round_trip(self):
		e, inv, doc, _ = generated(F.credit_note("0f0b4d6a-29ef-5a24-a7a3-0d3d4b6f2f5e"))
		back = e.normalize_invoice(e.parse_document(doc["content"]))
		self.assertEqual(back["document"]["document_type"], "CREDIT_NOTE")
		self.assertEqual(back["document"]["uuid"], doc["document_uuid"])
		self.assertEqual(back["references"]["credit_reason_code"], "CAN")
		self.assertEqual(back["supplier"]["address"]["subdivision"], "MO")
		self.assertEqual(back["lines"][0]["industry_code"], "465101")
		self.assertEqual(back["lines"][0]["tax_amount"], inv["lines"][0]["tax_amount"])
		self.assertEqual(back["document"]["direction"], "INBOUND")

	def test_parse_rejects_dtd(self):
		with self.assertRaises(PermanentError):
			engine().parse_document('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><Invoice/>')


class TestValidation(unittest.TestCase):
	def test_valid_scenarios_have_no_errors(self):
		for name, build in F.SCENARIOS.items():
			with self.subTest(name):
				e, inv = prepared(build())
				self.assertEqual(errors(e.validate(inv)), [])

	def test_invalid_supplier_identifier(self):
		e, inv = prepared(F.invalid_supplier_vatin())
		self.assertIn("EIH-OM-016", errors(e.validate(inv)))

	def test_missing_buyer(self):
		e, inv = prepared(F.missing_buyer())
		found = errors(e.validate(inv))
		self.assertIn("EIH-OM-010", found)
		self.assertIn("EIH-OM-021", found)

	def test_wrong_line_vat(self):
		e, inv = prepared(F.bad_tax())
		self.assertIn("EIH-OM-060", errors(e.validate(inv)))

	def test_required_oman_terms(self):
		inv = F.standard()
		inv["document"].pop("issue_time")
		inv["supplier"]["contact"] = {}
		inv["supplier"]["address"].pop("address_line")
		inv["lines"][0].pop("industry_code")
		inv["lines"][0]["commodity_code"] = "8471"
		e, out = prepared(inv)
		found = errors(e.validate(out))
		for rule in ("EIH-OM-004", "EIH-OM-017", "EIH-OM-012", "EIH-OM-054", "EIH-OM-053"):
			self.assertIn(rule, found)

	def test_credit_note_requires_reason_and_original_uuid(self):
		inv = F.credit_note(None)
		inv["references"].pop("credit_reason_code")
		e, out = prepared(inv)
		found = errors(e.validate(out))
		self.assertIn("EIH-OM-030", found)
		self.assertIn("EIH-OM-031", found)

	def test_transaction_type_conflicts(self):
		inv = F.standard()
		inv["extensions"] = {"om": {"transaction_types": ["FULL_TAX_INVOICE", "SIMPLIFIED_TAX_INVOICE"]}}
		e, out = prepared(inv)
		self.assertIn("EIH-OM-008", errors(e.validate(out)))
		inv["extensions"] = {"om": {"transaction_types": ["FULL_TAX_INVOICE", "EXPORT", "IMPORT_OF_GOODS"]}}
		e, out = prepared(inv)
		self.assertIn("EIH-OM-009", errors(e.validate(out)))

	def test_future_date_and_foreign_rate(self):
		e, out = prepared(F.invoice(invoice_date="2099-01-01"))
		self.assertIn("EIH-OM-003", errors(e.validate(out)))
		e, out = prepared(F.invoice(currency="USD"))
		self.assertIn("EIH-OM-006", errors(e.validate(out)))

	def test_official_check_reports_when_not_configured(self):
		e, inv, doc, _ = generated(F.standard())
		issues = e.validate_document(doc, inv)
		self.assertEqual([(i["severity"], i["rule_id"]) for i in issues], [("Warning", "EIH-OM-090")])
		self.assertEqual(engine(official_validation="off").validate_document(doc, inv), [])
		required = engine(official_validation="required").validate_document(doc, inv)
		self.assertEqual(required[0]["severity"], "Error")


class TestERPNextOman(unittest.TestCase):
	def connector(self, extra):
		c = ERPNextConnector.__new__(ERPNextConnector)
		c.extra, c.mapping = extra, None
		return c

	def test_oman_options(self):
		c = self.connector({"default_country": "OM",
			"tax_category_map": {"Zero Food": {"category": "ZERO_RATED", "exemption_reason_code": "VATZR-OM-01"}},
			"item_field_map": {"item_type": "custom_om_item_type", "industry_code": "custom_isic"},
			"credit_reason_field": "custom_reason", "b2c_field": "custom_b2c"})
		inv = {"name": "SINV-0001", "is_return": 1, "currency": "OMR", "posting_date": "2026-11-15",
			"posting_time": "9:05:07.123456", "return_against": "SINV-0000", "custom_reason": "QTY", "custom_b2c": 0,
			"taxes": [{"charge_type": "On Net Total", "rate": 5}],
			"items": [{"item_code": "A", "item_name": "Rice", "qty": -1, "net_rate": 1.255, "net_amount": -1.255,
				"item_tax_template": "Zero Food", "item_tax_rate": '{"VAT": 0}', "custom_om_item_type": "G",
				"custom_isic": "463001"},
				{"item_code": "B", "item_name": "Pen", "qty": -3, "net_rate": 0.333, "net_amount": -0.999}]}
		out = c.normalize_invoice(inv)
		self.assertEqual(out["document"]["issue_time"], "09:05:07")
		self.assertEqual(out["references"]["credit_reason_code"], "QTY")
		self.assertEqual(out["lines"][0]["tax_category"], "ZERO_RATED")
		self.assertEqual(out["lines"][0]["exemption_reason_code"], "VATZR-OM-01")
		self.assertEqual((out["lines"][0]["item_type"], out["lines"][0]["industry_code"]), ("G", "463001"))
		self.assertEqual(out["lines"][1]["tax_amount"], 0.05)  # 0.999 x 5% = 0.04995 -> 3 decimals for OMR
		self.assertEqual(out["extensions"], {})

	def test_uae_mapping_unchanged(self):
		c = self.connector({"tax_category_map": {"UAE Zero": "ZERO_RATED"}})
		out = c.normalize_invoice({"name": "S1", "currency": "AED", "taxes": [{"charge_type": "On Net Total", "rate": 5}],
			"items": [{"qty": 1, "net_rate": 10.005, "net_amount": 10.005}, {"qty": 1, "net_rate": 3, "net_amount": 3,
				"item_tax_template": "UAE Zero", "item_tax_rate": '{"VAT": 0}'}]})
		self.assertEqual(out["lines"][0]["tax_amount"], 0.5)
		self.assertEqual(out["lines"][1]["tax_category"], "ZERO_RATED")
		self.assertNotIn("exemption_reason_code", out["lines"][1])


@unittest.skipUnless(os.environ.get("OM_PINT_RESOURCES"), "set OM_PINT_RESOURCES to the official PINT OM resources")
class TestOfficialSchematron(unittest.TestCase):
	def test_all_fixtures_pass_official_rules(self):
		settings = {"schematron_dir": os.environ["OM_PINT_RESOURCES"],
			"selfbilling_schematron_dir": os.environ.get("OM_PINT_SB_RESOURCES"), "official_validation": "required"}
		cases = dict(F.SCENARIOS)
		cases["credit_note"] = lambda: F.credit_note(generated(F.standard())[2]["document_uuid"])
		for name, build in cases.items():
			with self.subTest(name):
				e, inv, doc, _ = generated(build(), **settings)
				self.assertEqual(e.validate_document(doc, inv), [], name)

	def test_official_rules_catch_a_bad_hs_code(self):
		inv = F.standard()
		inv["lines"][0]["commodity_code"] = "999999999999"
		e, out, doc, _ = generated(inv, schematron_dir=os.environ["OM_PINT_RESOURCES"])
		self.assertIn("CL-08-OM-HS", errors(e.validate_document(doc, out)))


if __name__ == "__main__":
	unittest.main()


@unittest.skipUnless(os.environ.get("UBL21_XSD_DIR") and os.environ.get("CCTS_XSD"),
	"set UBL21_XSD_DIR (folder with maindoc/ and common/) and CCTS_XSD; needs the xmlschema package")
class TestUBLSchema(unittest.TestCase):
	def test_generated_documents_are_ubl21_schema_valid(self):
		import warnings

		import xmlschema

		warnings.simplefilter("ignore")
		loc = [("urn:un:unece:uncefact:data:specification:CoreComponentTypeSchemaModule:2", os.environ["CCTS_XSD"])]
		root = os.environ["UBL21_XSD_DIR"]
		schemas = {name: xmlschema.XMLSchema(os.path.join(root, "maindoc", f"UBL-{name}-2.1.xsd"), locations=loc,
			validation="lax") for name in ("Invoice", "CreditNote")}
		cases = dict(F.SCENARIOS)
		cases["credit_note"] = lambda: F.credit_note(generated(F.standard())[2]["document_uuid"])
		for name, build in cases.items():
			with self.subTest(name):
				doc = generated(build())[2]["content"]
				kind = "CreditNote" if "<CreditNote" in doc else "Invoice"
				self.assertEqual([str(e.reason) for e in schemas[kind].iter_errors(doc)], [])
