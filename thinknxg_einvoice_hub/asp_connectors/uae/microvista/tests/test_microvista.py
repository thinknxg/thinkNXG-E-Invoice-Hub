"""Microvista adapter tests.

IMPORTANT: Microvista's API contract is not public. Every endpoint, field and response used
below is a MOCK defined in ``thinknxg_einvoice_hub.tests.mock_asp`` to prove that the adapter
runs whatever contract is configured. Nothing here documents the real Microvista API. Replace
MOCK_CONTRACT and the mock server with official sandbox fixtures when they are supplied
(checklist item MV-15).

    python -m unittest thinknxg_einvoice_hub.asp_connectors.uae.microvista.tests.test_microvista
"""

import copy
import hashlib
import hmac
import unittest

from thinknxg_einvoice_hub.asp_connectors.adapter_registry import get_adapter_class
from thinknxg_einvoice_hub.asp_connectors.uae.microvista import config
from thinknxg_einvoice_hub.asp_connectors.uae.microvista.adapter import MicrovistaAdapter
from thinknxg_einvoice_hub.asp_connectors.uae.microvista.exceptions import MicrovistaContractPending
from thinknxg_einvoice_hub.exceptions import PermanentError, TransientError
from thinknxg_einvoice_hub.tests import mock_asp

INVOICE = {"document": {"invoice_number": "INV-MV-1", "document_type": "INVOICE"}, "lines": []}


def mock_contract(base_url):
	"""MOCK contract - invented for tests, not Microvista's API."""
	return {
		"name": "Microvista (MOCK contract)", "code": "microvista", "base_url": base_url, "environment": "Sandbox",
		"allowed_hosts": ["127.0.0.1"], "allow_insecure": True, "allow_private_hosts": True, "verify_ssl": True,
		"auth": {"type": "Bearer Token", "api_secret": "static-token"},
		"participant": {"participant_id": "MOCK-PARTICIPANT"},
		"endpoints": {
			"Verify Credentials": {"method": "GET", "url": "/verify", "enabled": 1},
			"Submit Invoice": {"method": "POST", "url": "/invoices", "enabled": 1, "retry": 1, "max_retries": 2,
				"idempotency": 1, "idempotency_header": "Idempotency-Key"},
			"Submit Credit Note": {"method": "POST", "url": "/credit-notes", "enabled": 1, "idempotency": 1},
			"Get Invoice Status": {"method": "GET", "url": "/invoices/{document_id}", "enabled": 1},
			"Download XML": {"method": "GET", "url": "/invoices/{document_id}/xml", "enabled": 1},
			"Download PDF": {"method": "GET", "url": "/invoices/{document_id}/pdf", "enabled": 1},
			"Slow": {"method": "GET", "url": "/slow", "enabled": 1, "timeout": 1},
			"Limited": {"method": "GET", "url": "/ratelimit", "enabled": 1, "retry": 0},
		},
		"request_mappings": [
			{"operation": op, "source": "invoice.document.invoice_number", "target": "invoice_number", "required": 1}
			for op in ("Submit Invoice", "Submit Credit Note")
		],
		"response_mappings": [
			{"path": "document_id", "target": "asp_document_id"},
			{"operation": "Get Invoice Status", "path": "id", "target": "asp_document_id"},
			{"path": "status", "target": "submission_status", "transformation": 'map:{"queued": "ACCEPTED", "*": "REJECTED"}'},
			{"path": "success", "target": "success"},
			{"path": "error", "target": "error_message"},
			{"path": "tdd_status", "target": "fta_status"},
			{"path": "delivery_status", "target": "delivery_status"},
		],
		"webhook": {"enabled": 1, "auth_type": "HMAC-SHA256", "header": "X-Mock-Signature", "event_id_path": "event_id",
			"event_type_path": "event", "document_id_path": "document_id", "status_path": "status"},
	}


class TestMicrovistaWithoutContract(unittest.TestCase):
	"""What ships today: a selectable provider that refuses to transmit and says why."""

	def test_registered_with_true_status(self):
		cls = get_adapter_class("microvista")
		self.assertIs(cls, MicrovistaAdapter)
		self.assertEqual((cls.status, cls.accreditation_number, cls.legal_name),
			("Development", "157529", "Microvista Technologies LLC"))

	def test_refuses_to_transmit_without_a_verified_contract(self):
		adapter = MicrovistaAdapter({"name": "ASPC-MV"})
		for call in (lambda: adapter.submit_invoice("<xml/>", {"_canonical": INVOICE}),
				lambda: adapter.submit_credit_note("<xml/>", {"_canonical": INVOICE}),
				lambda: adapter.get_document_status("X"), adapter.verify_credentials):
			with self.assertRaises(MicrovistaContractPending):
				call()

	def test_readiness_report(self):
		report = MicrovistaAdapter({"name": "ASPC-MV"}).readiness()
		self.assertFalse(report["ready_for_sandbox"])
		self.assertFalse(report["production_ready"])
		self.assertEqual(len(report["checklist"]), 15)
		self.assertEqual(report["integration_status"], config.INTEGRATION_STATUS)
		self.assertTrue(any("MV-02" in item for item in report["blocking"]))


class TestMicrovistaWithMockContract(unittest.TestCase):
	"""The adapter running a MOCK contract end to end (simulated responses, not Microvista's)."""

	@classmethod
	def setUpClass(cls):
		cls.server, cls.state, cls.url = mock_asp.start()

	@classmethod
	def tearDownClass(cls):
		cls.server.shutdown()

	def adapter(self, secret="mock-webhook-secret", **auth):
		rest = mock_contract(self.url)
		rest["auth"].update(auth)
		adapter = MicrovistaAdapter({"name": "ASPC-MV", "webhook_secret": secret, "rest": rest})
		adapter.engine.sleep = lambda seconds: None
		return adapter

	def meta(self, number="INV-MV-1", key="EINV-MV-1"):
		invoice = copy.deepcopy(INVOICE)
		invoice["document"]["invoice_number"] = number
		return {"transaction": key, "idempotency_key": key, "_canonical": invoice}

	def test_ready_for_sandbox_but_never_production_ready_by_itself(self):
		report = self.adapter().readiness()
		self.assertTrue(report["ready_for_sandbox"], report["blocking"])
		self.assertFalse(report["production_ready"])

	def test_credentials(self):
		self.assertIn("verified", self.adapter().verify_credentials())
		with self.assertRaises(PermanentError) as ctx:
			self.adapter(api_secret="bad-credential-value").verify_credentials()
		self.assertNotIn("bad-credential-value", str(ctx.exception))

	def test_invoice_and_credit_note_submission(self):
		adapter = self.adapter()
		invoice = adapter.submit_invoice("<xml/>", self.meta())
		self.assertEqual(invoice["status"], "ACCEPTED")
		note = adapter.submit_credit_note("<xml/>", self.meta("CN-MV-1", "EINV-MV-2"))
		self.assertEqual(note["raw"]["kind"], "credit_note")
		self.assertNotEqual(invoice["reference"], note["reference"])

	def test_repeated_submission_does_not_create_a_second_document(self):
		adapter = self.adapter()
		first = adapter.submit_invoice("<xml/>", self.meta("INV-MV-DUP", "EINV-MV-DUP"))
		second = adapter.submit_invoice("<xml/>", self.meta("INV-MV-DUP", "EINV-MV-DUP"))
		self.assertEqual(first["reference"], second["reference"])

	def test_status_and_document_retrieval(self):
		adapter = self.adapter()
		reference = adapter.submit_invoice("<xml/>", self.meta("INV-MV-ST", "EINV-MV-ST"))["reference"]
		status = adapter.get_document_status(reference)
		self.assertEqual((status["fta_status"], status["delivery_status"]), ("REPORTED", "DELIVERED"))
		self.assertIn("<Invoice>", adapter.get_document_xml(reference))
		self.assertEqual(adapter.get_document_pdf(reference)[:4], b"%PDF")

	def test_webhook_signature_and_event(self):
		adapter = self.adapter()
		body = b'{"event_id": "e-1", "event": "status", "document_id": "DOC-0001", "status": "delivered"}'
		good = hmac.new(b"mock-webhook-secret", body, hashlib.sha256).hexdigest()
		self.assertTrue(adapter.verify_webhook(body, {"X-Mock-Signature": good}))
		self.assertFalse(adapter.verify_webhook(body, {"X-Mock-Signature": "0" * 64}))
		self.assertFalse(adapter.verify_webhook(body, {}))
		self.assertFalse(self.adapter(secret=None).verify_webhook(body, {"X-Mock-Signature": good}))
		event = adapter.process_webhook({"event_id": "e-1", "event": "status", "document_id": "DOC-0001", "status": "delivered"})
		self.assertEqual((event["event_id"], event["reference"], event["status"]), ("e-1", "DOC-0001", "DELIVERED"))

	def test_timeout_and_rate_limit_are_retryable_failures(self):
		adapter = self.adapter()
		with self.assertRaises(TransientError):
			adapter._run("Slow")
		self.state.fail_once.discard("ratelimit")
		with self.assertRaises(TransientError) as ctx:
			adapter._run("Limited")
		self.assertIn("429", str(ctx.exception))


if __name__ == "__main__":
	unittest.main()
