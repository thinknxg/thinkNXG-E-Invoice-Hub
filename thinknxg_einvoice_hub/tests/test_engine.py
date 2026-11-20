"""Framework-independent tests for the canonical model, mapping and UAE PINT AE engine.

Run from the app folder without a bench:  python -m unittest thinknxg_einvoice_hub.tests.test_engine
"""

import copy
import unittest
import xml.dom.minidom

from thinknxg_einvoice_hub.asp_connectors.sandbox.adapter import SandboxAdapter
from thinknxg_einvoice_hub.canonical.invoice_schema import validate_structure
from thinknxg_einvoice_hub.canonical.mapper import apply_mapping
from thinknxg_einvoice_hub.canonical.normalizer import normalize
from thinknxg_einvoice_hub.compliance.registry import get_engine
from thinknxg_einvoice_hub.exceptions import MappingError, PermanentError, TransientError
from thinknxg_einvoice_hub.utils import has_errors

INVOICE = {
	"schema_version": "1.0",
	"document": {"document_type": "INVOICE", "invoice_number": "INV-1", "invoice_date": "2026-11-11",
		"due_date": "2026-12-11", "currency": "AED"},
	"supplier": {"legal_name": "ABC Trading LLC", "tax_id": "100000000000003",
		"legal_registration_id": "CN-1234567", "legal_registration_type": "TL",
		"legal_registration_authority": "Dubai Department of Economy and Tourism",
		"address": {"street": "Sheikh Zayed Road", "city": "Dubai", "subdivision": "DXB", "country": "AE"}},
	"customer": {"legal_name": "XYZ LLC", "tax_id": "100234567800003",
		"address": {"street": "Corniche Road", "city": "Abu Dhabi", "subdivision": "AUH", "country": "AE"}},
	"lines": [{"item_name": "Consulting", "quantity": 2, "unit_price": 1000, "tax_category": "STANDARD", "tax_rate": 5}],
}


def prepared(inv=None):
	engine = get_engine("uae_pint_ae")
	return engine, engine.enrich(normalize(inv or INVOICE))


def errors(issues):
	return sorted({i["rule_id"] for i in issues if i["severity"] == "Error"})


class TestCanonical(unittest.TestCase):
	def test_normalizer_derives_amounts(self):
		inv = normalize(INVOICE)
		self.assertEqual(inv["lines"][0]["net_amount"], 2000.0)
		self.assertEqual(inv["lines"][0]["tax_amount"], 100.0)
		self.assertEqual(inv["totals"]["grand_total"], 2100.0)
		self.assertEqual(inv["tax_breakdown"][0]["taxable_amount"], 2000.0)
		self.assertEqual(validate_structure(inv), [])

	def test_normalizer_keeps_erp_amounts(self):
		inv = copy.deepcopy(INVOICE)
		inv["totals"] = {"grand_total": 5000}
		self.assertEqual(normalize(inv)["totals"]["grand_total"], 5000.0)

	def test_credit_note_signs_are_flipped(self):
		inv = copy.deepcopy(INVOICE)
		inv["document"]["document_type"] = "credit_note"
		inv["lines"][0]["quantity"] = -2
		inv["references"] = {"original_invoice_number": "INV-0"}
		out = normalize(inv)
		self.assertEqual(out["document"]["document_type"], "CREDIT_NOTE")
		self.assertEqual(out["lines"][0]["quantity"], 2.0)
		self.assertEqual(out["totals"]["grand_total"], 2100.0)

	def test_structure_errors(self):
		inv = copy.deepcopy(INVOICE)
		inv["lines"] = []
		del inv["document"]["invoice_number"]
		self.assertEqual(errors(validate_structure(normalize(inv))), ["CAN-002", "CAN-010"])

	def test_mapping(self):
		mapping = {"line_source_path": "rows", "defaults": {"document": {"currency": "AED"}}, "rules": [
			{"scope": "Header", "source_path": "no", "canonical_path": "document.invoice_number", "required": 1},
			{"scope": "Header", "source_path": "dt", "canonical_path": "document.invoice_date", "transform": "Date",
				"transform_arg": "%d/%m/%Y"},
			{"scope": "Line", "source_path": "q", "canonical_path": "quantity", "transform": "Number"},
			{"scope": "Line", "source_path": "vat", "canonical_path": "tax_category", "transform": "Value Map",
				"transform_arg": '{"A": "STANDARD"}'},
		]}
		inv = apply_mapping({"no": "X-1", "dt": "11/11/2026", "rows": [{"q": "1,250.5", "vat": "A"}]}, mapping)
		self.assertEqual(inv["document"], {"document_type": "INVOICE", "invoice_kind": "TAX", "direction": "OUTBOUND",
			"currency": "AED", "invoice_number": "X-1", "invoice_date": "2026-11-11"})
		self.assertEqual(inv["lines"], [{"quantity": 1250.5, "tax_category": "STANDARD"}])
		with self.assertRaises(MappingError):
			apply_mapping({"rows": []}, mapping)


class TestPintAE(unittest.TestCase):
	def test_enrich_and_validate(self):
		engine, inv = prepared()
		self.assertEqual(inv["supplier"]["tin"], "1000000000")
		self.assertEqual(engine.participant_id(inv["customer"]), "0235:1002345678")
		self.assertFalse(has_errors(engine.validate(inv)))

	def test_validation_rules(self):
		bad = copy.deepcopy(INVOICE)
		bad["supplier"]["tax_id"] = "123"
		bad["customer"]["address"].pop("subdivision")
		bad["lines"][0].update({"tax_category": "ZERO_RATED"})
		bad["totals"] = {"grand_total": 1}
		engine, inv = prepared(bad)
		self.assertEqual(errors(engine.validate(inv)),
			["EIH-AE-013", "EIH-AE-016", "EIH-AE-017", "EIH-AE-043", "EIH-AE-052"])

	def test_ubl_round_trip(self):
		engine, inv = prepared()
		xml_text = engine.generate_document(inv)["content"]
		xml.dom.minidom.parseString(xml_text)
		self.assertIn("<cbc:CustomizationID>urn:peppol:pint:billing-1@ae-1</cbc:CustomizationID>", xml_text)
		self.assertIn("<cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>", xml_text)
		self.assertIn('<cbc:EndpointID schemeID="0235">1000000000</cbc:EndpointID>', xml_text)
		back = engine.enrich(normalize(engine.parse_document(xml_text)))
		self.assertEqual(back["totals"], inv["totals"])
		self.assertEqual(back["document"]["direction"], "INBOUND")
		self.assertEqual(back["customer"]["tax_id"], "100234567800003")
		self.assertFalse(has_errors(engine.validate(back)))

	def test_credit_note_and_foreign_currency(self):
		cn = copy.deepcopy(INVOICE)
		cn["document"].update({"document_type": "CREDIT_NOTE", "currency": "USD", "exchange_rate": 3.6725})
		cn["references"] = {"original_invoice_number": "INV-0", "credit_reason_code": "DL8.61.1.C"}
		engine, inv = prepared(cn)
		self.assertFalse(has_errors(engine.validate(inv)))
		xml_text = engine.generate_document(inv)["content"]
		self.assertIn("<CreditNote ", xml_text)
		self.assertIn("<cbc:CreditNoteTypeCode>381</cbc:CreditNoteTypeCode>", xml_text)
		self.assertIn('<cbc:TaxAmount currencyID="AED">367.25</cbc:TaxAmount>', xml_text)
		self.assertEqual(engine.parse_document(xml_text)["references"]["original_invoice_number"], "INV-0")
		del cn["references"]
		self.assertIn("CAN-020", errors(engine.validate(prepared(cn)[1])))

	def test_xml_escaping_and_dtd_refusal(self):
		inv = copy.deepcopy(INVOICE)
		inv["customer"]["legal_name"] = "A & B <Trading>"
		engine, inv = prepared(inv)
		xml_text = engine.generate_document(inv)["content"]
		self.assertEqual(engine.parse_document(xml_text)["customer"]["legal_name"], "A & B <Trading>")
		with self.assertRaises(PermanentError):
			engine.parse_document('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><Invoice/>')


class TestSandboxAdapter(unittest.TestCase):
	def test_behaviours(self):
		adapter = SandboxAdapter({"environment": "Sandbox"})
		self.assertEqual(adapter.submit_document("<x/>", {"invoice_number": "INV-1"})["status"], "DELIVERED")
		self.assertEqual(adapter.submit_document("<x/>", {"invoice_number": "INV-REJECT"})["status"], "REJECTED")
		self.assertEqual(adapter.submit_document("<x/>", {"invoice_number": "INV-PENDING"})["status"], "SUBMITTED")
		with self.assertRaises(TransientError):
			adapter.submit_document("<x/>", {"invoice_number": "INV-TIMEOUT"})
		with self.assertRaises(PermanentError):
			SandboxAdapter({"environment": "Production"}).submit_document("<x/>", {})


if __name__ == "__main__":
	unittest.main()
