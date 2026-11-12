"""Consistency checks for shipped presets and directory data (no network).

These prove that a preset's mapping rules produce a body from a canonical invoice. They do NOT
prove that the provider accepts that body: no preset has been run against a provider sandbox.
"""

import json
import os
import unittest

from thinknxg_einvoice_hub.canonical.normalizer import normalize
from thinknxg_einvoice_hub.compliance.registry import get_engine
from thinknxg_einvoice_hub.services.asp_rest_engine import ASPRestEngine, apply_request_mappings, transformations

ROOT = os.path.dirname(os.path.dirname(__file__))


class TestWafeqPreset(unittest.TestCase):
	def setUp(self):
		with open(os.path.join(ROOT, "asp_connectors", "uae", "wafeq", "preset.json"), encoding="utf-8") as handle:
			self.preset = json.load(handle)
		with open(os.path.join(os.path.dirname(ROOT), "samples", "canonical_invoice.json"), encoding="utf-8") as handle:
			engine = get_engine("uae_pint_ae")
			self.invoice = engine.enrich(normalize(json.load(handle)))
			self.receiver = engine.participant_id(self.invoice["customer"])

	def rules(self):
		return [{"operation": r["operation"], "source": r["source_field"], "target": r["target_json_path"],
			"data_type": r.get("data_type"), "transformation": r.get("transformation"), "condition": r.get("condition"),
			"required": r.get("required"), "default": r.get("default_value"), "enabled": r.get("enabled", 1)}
			for r in self.preset["request_mappings"]]

	def test_request_body_is_built_from_the_canonical_invoice(self):
		context = {"invoice": self.invoice, "metadata": {"transaction": "EINV-1", "receiver_id": self.receiver}}
		body = apply_request_mappings(self.rules(), "Submit Invoice", context, transformations())
		self.assertEqual(body["invoice_number"], "INV-2026-001")
		self.assertEqual(body["customer"]["id"], "0235:1002345678")
		self.assertEqual(body["line_items"], [{"description": "Consulting Service", "quantity": 2.0, "unit_price": 1000.0,
			"tax_category": "S", "tax_percent": 5.0}])
		self.assertNotIn("currency_exchange_rate", body)  # AED invoice
		self.assertNotIn("supplier", body)                # the provider derives the seller from the taxpayer

	def test_status_values_from_the_documentation_map_to_platform_statuses(self):
		rules = [{"path": r["response_json_path"], "target": r["target_platform_field"], "operation": r.get("operation"),
			"transformation": r.get("transformation"), "enabled": 1} for r in self.preset["response_mappings"]]
		engine = ASPRestEngine()
		submit = lambda status: engine.map_response({"response_mappings": rules},
			{"document_id": "d1", "status": status}, "Submit Invoice")
		self.assertEqual(submit("queued"), {"asp_document_id": "d1", "submission_status": "ACCEPTED", "delivery_status": "PENDING"})
		self.assertEqual(submit("failed"), {"asp_document_id": "d1", "submission_status": "ACCEPTED", "delivery_status": "FAILED"})
		self.assertEqual(submit("reporting_only"), {"asp_document_id": "d1", "submission_status": "ACCEPTED"})
		self.assertEqual(submit("anything_else")["submission_status"], "REJECTED")
		track = engine.map_response({"response_mappings": rules},
			{"id": "d1", "tdd_status": "reported", "delivery_status": "delivered_confirmed"}, "Get Invoice Status")
		self.assertEqual(track, {"asp_document_id": "d1", "fta_status": "REPORTED", "delivery_status": "DELIVERED"})


class TestDirectoryData(unittest.TestCase):
	def test_directory_file(self):
		rows = []
		with open(os.path.join(ROOT, "data", "uae_asp_directory.txt"), encoding="utf-8") as handle:
			rows = [line.strip().split("|") for line in handle if line.strip() and not line.startswith("#")]
		self.assertEqual(len(rows), 86)
		numbers = [r[1] for r in rows]
		self.assertEqual(len(set(numbers)), 86)
		self.assertTrue(all(n.isdigit() and len(n) == 6 for n in numbers))
		self.assertIn(["Microvista Technologies LLC", "157529", "microvistatech.com/e-invoicing-in-uae", "microvista"], rows)


if __name__ == "__main__":
	unittest.main()
