"""Tests for the configuration-driven REST engine, run against the MOCK ASP in ``mock_asp.py``.

    python -m unittest thinknxg_einvoice_hub.tests.test_rest_engine
"""

import base64
import copy
import hashlib
import hmac
import json
import time
import unittest

from thinknxg_einvoice_hub.asp_connectors.generic_rest.configured import ConfiguredRestAdapter
from thinknxg_einvoice_hub.exceptions import MappingError, NotSupportedError, PermanentError, TransientError
from thinknxg_einvoice_hub.services.asp_rest_engine import ASPRestEngine, apply_request_mappings, mask, transform
from thinknxg_einvoice_hub.tests import mock_asp
from thinknxg_einvoice_hub.webhook_security import verify_configured, verify_jwt_hs256

INVOICE = {
	"document": {"invoice_number": "INV-1", "invoice_date": "2026-11-11", "currency": "AED", "document_type": "INVOICE"},
	"customer": {"legal_name": "XYZ LLC", "tin": "1002345678"},
	"lines": [
		{"item_name": "A", "quantity": 2, "unit_price": 10.5, "tax_category": "STANDARD"},
		{"item_name": "B", "quantity": 1, "unit_price": 100, "tax_category": "ZERO_RATED"},
	],
}
MAPPINGS = [
	{"operation": "Submit Invoice", "source": "invoice.document.invoice_number", "target": "invoice_number", "required": 1},
	{"operation": "Submit Invoice", "source": "invoice.document.invoice_date", "target": "dates.issue", "transformation": "date:%d/%m/%Y"},
	{"operation": "Submit Invoice", "source": "invoice.customer.tin", "target": "customer.id", "transformation": "prefix:0235:"},
	{"operation": "Submit Invoice", "source": "invoice.lines[].item_name", "target": "items[].description"},
	{"operation": "Submit Invoice", "source": "invoice.lines[].quantity", "target": "items[].qty", "data_type": "Decimal"},
	{"operation": "Submit Invoice", "source": "invoice.lines[].unit_price", "target": "items[].price.amount", "transformation": "decimal:2"},
	{"operation": "Submit Invoice", "source": "invoice.lines[].tax_category", "target": "items[].vat", "transformation": "uae_tax_code"},
	{"operation": "Submit Invoice", "source": "", "target": "channel", "transformation": "const:api"},
	{"operation": "Submit Invoice", "source": "invoice.document.currency", "target": "foreign", "transformation": "const:true",
		"data_type": "Boolean", "condition": "invoice.document.currency != AED"},
	{"operation": "Submit Invoice", "source": "$idempotency_key", "target": "client_reference"},
]
RESPONSES = [
	{"path": "document_id", "target": "asp_document_id"},
	{"operation": "Get Invoice Status", "path": "id", "target": "asp_document_id"},
	{"operation": "Submit Invoice", "path": "status", "target": "submission_status",
		"transformation": 'map:{"queued": "ACCEPTED", "*": "REJECTED"}'},
	{"path": "success", "target": "success"},
	{"path": "error", "target": "error_message"},
	{"path": "code", "target": "error_code"},
	{"path": "tdd_status", "target": "fta_status"},
	{"path": "delivery_status", "target": "delivery_status"},
]


class RestEngineCase(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.server, cls.state, cls.url = mock_asp.start()

	@classmethod
	def tearDownClass(cls):
		cls.server.shutdown()

	def setUp(self):
		self.state.requests.clear()
		self.state.fail_once.clear()
		self.logs = []
		self.sleeps = []
		self.engine = ASPRestEngine(logger=self.logs.append, sleep=self.sleeps.append)

	def config(self, auth=None, **overrides):
		cfg = {
			"name": "Mock ASP", "code": "mock", "base_url": self.url, "allowed_hosts": ["127.0.0.1"],
			"allow_insecure": True, "allow_private_hosts": True, "verify_ssl": True,
			"auth": {"type": "Bearer Token", "api_secret": "static-token", **(auth or {})},
			"endpoints": {
				"Verify Credentials": {"method": "GET", "url": "/verify", "enabled": 1},
				"Submit Invoice": {"method": "POST", "url": "/invoices", "enabled": 1, "retry": 1, "max_retries": 2,
					"idempotency": 1, "idempotency_header": "Idempotency-Key"},
				"Get Invoice Status": {"method": "GET", "url": "/invoices/{document_id}", "enabled": 1, "retry": 1,
					"max_retries": 2},
				"Download XML": {"method": "GET", "url": "/invoices/{document_id}/xml", "enabled": 1},
				"Download PDF": {"method": "GET", "url": "/invoices/{document_id}/pdf", "enabled": 1},
			},
			"headers": [{"name": "X-Tenant", "value_type": "Dynamic", "dynamic_value": "participant.participant_id", "enabled": 1},
				{"name": "X-Static", "value": "yes", "enabled": 1}],
			"request_mappings": copy.deepcopy(MAPPINGS), "response_mappings": copy.deepcopy(RESPONSES),
		}
		cfg.update(overrides)
		return cfg

	def context(self, invoice=None, key="KEY-1"):
		return {"invoice": invoice or INVOICE, "idempotency_key": key,
			"participant": {"participant_id": "P-77"}, "metadata": {}}

	def last(self, method="POST", path="/invoices"):
		return self.state.calls(method, path)[-1]


class TestAuthentication(RestEngineCase):
	def verify(self, auth):
		return self.engine.execute(self.config(auth), "Verify Credentials", context=self.context())

	def test_api_key(self):
		self.verify({"type": "API Key", "api_key": "k-123"})
		self.assertEqual(self.last("GET", "/verify")[2]["X-API-Key"], "k-123")
		self.verify({"type": "API Key", "api_key": "k-123", "api_key_header": "Authorization", "api_key_prefix": "Api-Key "})
		self.assertEqual(self.last("GET", "/verify")[2]["Authorization"], "Api-Key k-123")

	def test_bearer_and_basic(self):
		self.verify({"type": "Bearer Token", "api_secret": "static-token"})
		self.assertEqual(self.last("GET", "/verify")[2]["Authorization"], "Bearer static-token")
		self.verify({"type": "Basic", "username": "u", "password": "p"})
		self.assertEqual(self.last("GET", "/verify")[2]["Authorization"], "Basic " + base64.b64encode(b"u:p").decode())

	def test_wrong_credentials_fail_permanently(self):
		with self.assertRaises(PermanentError) as ctx:
			self.verify({"type": "Bearer Token", "api_secret": "wrong-secret-value"})
		self.assertIn("401", str(ctx.exception))
		self.assertNotIn("wrong-secret-value", str(ctx.exception))

	def test_oauth2_client_credentials_caches_and_refreshes(self):
		auth = {"type": "OAuth2 Client Credentials", "client_id": "cid", "client_secret": "csecret-value",
			"token_url": "/oauth/token", "scope": "invoices:write"}
		before = self.state.tokens_issued
		self.verify(auth)
		self.verify(auth)
		self.assertEqual(self.state.tokens_issued, before + 1, "token must be cached between calls")
		form = self.last("POST", "/oauth/token")[3].decode()
		self.assertIn("grant_type=client_credentials", form)
		self.assertIn("scope=invoices%3Awrite", form)
		# the provider rejects the cached token once: the engine fetches a new one and repeats the call
		self.state.expire_next_token = True
		self.verify(auth)
		self.assertEqual(self.state.tokens_issued, before + 2)

	def test_oauth2_authorization_code_uses_refresh_token(self):
		self.verify({"type": "OAuth2 Authorization Code", "client_id": "cid", "client_secret": "cs", "refresh_token": "rt-1",
			"token_url": "/oauth/token", "token_content_type": "application/json"})
		body = json.loads(self.last("POST", "/oauth/token")[3])
		self.assertEqual((body["grant_type"], body["refresh_token"]), ("refresh_token", "rt-1"))
		with self.assertRaises(PermanentError):
			self.verify({"type": "OAuth2 Authorization Code", "client_id": "other", "token_url": "/oauth/token"})

	def test_custom_headers(self):
		self.verify({"type": "Custom Header", "api_key": "abc", "custom_headers": {"X-Custom-Auth": "Key {api_key}"}})
		self.assertEqual(self.last("GET", "/verify")[2]["X-Custom-Auth"], "Key abc")

	def test_hmac_sha256(self):
		self.verify({"type": "HMAC-SHA256", "api_key": "kid", "api_secret": "hmac-secret"})
		headers = self.last("GET", "/verify")[2]
		message = f"{headers['X-Timestamp']}.GET./verify."
		expected = hmac.new(b"hmac-secret", message.encode(), hashlib.sha256).hexdigest()
		self.assertEqual(headers["X-Signature"], expected)
		self.assertEqual(headers["X-API-Key"], "kid")

	def test_jwt_hs256(self):
		self.verify({"type": "JWT", "client_id": "issuer-1", "api_secret": "jwt-secret", "jwt_claims": {"aud": "asp"}})
		token = self.last("GET", "/verify")[2]["Authorization"][7:]
		self.assertTrue(verify_jwt_hs256(token, "jwt-secret"))
		self.assertFalse(verify_jwt_hs256(token, "other-secret"))
		claims = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
		self.assertEqual((claims["iss"], claims["aud"]), ("issuer-1", "asp"))

	def test_dynamic_and_static_headers(self):
		self.verify(None)
		headers = self.last("GET", "/verify")[2]
		self.assertEqual((headers["X-Tenant"], headers["X-Static"]), ("P-77", "yes"))


class TestMappings(RestEngineCase):
	def test_nested_arrays_conditions_and_dynamic_values(self):
		body = apply_request_mappings(MAPPINGS, "Submit Invoice", self.context())
		self.assertEqual(body, {
			"invoice_number": "INV-1", "dates": {"issue": "11/11/2026"}, "customer": {"id": "0235:1002345678"},
			"items": [{"description": "A", "qty": 2.0, "price": {"amount": "10.50"}, "vat": "S"},
				{"description": "B", "qty": 1.0, "price": {"amount": "100.00"}, "vat": "Z"}],
			"channel": "api", "client_reference": "KEY-1",
		})
		usd = copy.deepcopy(INVOICE)
		usd["document"]["currency"] = "USD"
		self.assertIs(apply_request_mappings(MAPPINGS, "Submit Invoice", self.context(usd))["foreign"], True)

	def test_required_field_and_unknown_transformation(self):
		broken = copy.deepcopy(INVOICE)
		del broken["document"]["invoice_number"]
		with self.assertRaises(MappingError):
			apply_request_mappings(MAPPINGS, "Submit Invoice", self.context(broken))
		with self.assertRaises(MappingError):
			transform("x", "__import__('os').system('id')")
		with self.assertRaises(MappingError):
			transform("x", "eval:1+1")

	def test_response_mapping_and_status_vocabulary(self):
		response = self.engine.execute(self.config(), "Submit Invoice", context=self.context())
		self.assertEqual(response["mapped"], {"asp_document_id": response["data"]["document_id"],
			"submission_status": "ACCEPTED"})
		status = self.engine.execute(self.config(), "Get Invoice Status", context=self.context(),
			path_params={"document_id": "DOC-0001"})
		self.assertEqual(status["mapped"], {"asp_document_id": "DOC-0001", "fta_status": "REPORTED",
			"delivery_status": "DELIVERED"})


class TestTransport(RestEngineCase):
	def test_idempotency_key_is_sent_and_stable(self):
		first = self.engine.execute(self.config(), "Submit Invoice", context=self.context(key="K-A"))
		again = self.engine.execute(self.config(), "Submit Invoice", context=self.context(key="K-A"))
		self.assertEqual(self.last()[2]["Idempotency-Key"], "K-A")
		self.assertEqual(first["mapped"]["asp_document_id"], again["mapped"]["asp_document_id"])

	def test_retry_with_backoff_then_success(self):
		flaky = copy.deepcopy(INVOICE)
		flaky["document"]["invoice_number"] = "INV-FLAKY-1"
		response = self.engine.execute(self.config(), "Submit Invoice", context=self.context(flaky, "K-F"))
		self.assertEqual(response["status"], 202)
		self.assertEqual(len(self.state.calls("POST", "/invoices")), 2)
		self.assertEqual(self.sleeps, [1.0])

	def test_post_without_idempotency_is_never_repeated(self):
		flaky = copy.deepcopy(INVOICE)
		flaky["document"]["invoice_number"] = "INV-FLAKY-2"
		cfg = self.config()
		cfg["endpoints"]["Submit Invoice"]["idempotency"] = 0
		with self.assertRaises(TransientError):
			self.engine.execute(cfg, "Submit Invoice", context=self.context(flaky, "K-G"))
		self.assertEqual(len(self.state.calls("POST", "/invoices")), 1)

	def test_rate_limit_honours_retry_after(self):
		cfg = self.config(endpoints={"Custom": {"method": "GET", "url": "/ratelimit", "enabled": 1, "retry": 1, "max_retries": 1}})
		self.assertEqual(self.engine.execute(cfg, "Custom", context=self.context())["status"], 200)
		self.assertEqual(self.sleeps, [0.0])

	def test_timeout_is_transient(self):
		cfg = self.config(endpoints={"Custom": {"method": "GET", "url": "/slow", "enabled": 1, "timeout": 1}})
		started = time.time()
		with self.assertRaises(TransientError):
			self.engine.execute(cfg, "Custom", context=self.context())
		self.assertLess(time.time() - started, 2.9)

	def test_http_error_invalid_json_redirect_and_size_limit(self):
		def custom(path, **cfg):
			return self.config(endpoints={"Custom": {"method": "GET", "url": path, "enabled": 1}}, **cfg)

		with self.assertRaises(PermanentError) as ctx:
			self.engine.execute(custom("/missing"), "Custom", context=self.context())
		self.assertIn("404", str(ctx.exception))
		with self.assertRaises(PermanentError):
			self.engine.execute(custom("/badjson"), "Custom", context=self.context())
		with self.assertRaises(PermanentError) as ctx:
			self.engine.execute(custom("/redirect"), "Custom", context=self.context())
		self.assertIn("redirect", str(ctx.exception))
		with self.assertRaises(PermanentError) as ctx:
			self.engine.execute(custom("/big", max_response_bytes=1000), "Custom", context=self.context())
		self.assertIn("limit", str(ctx.exception))

	def test_unsafe_urls_are_rejected(self):
		for cfg in (
			self.config(allow_insecure=False),                                   # plain http
			self.config(allowed_hosts=["api.example.com"]),                      # host not approved
			self.config(allow_private_hosts=False),                              # loopback address
			self.config(endpoints={"Verify Credentials": {"method": "GET", "url": "http://169.254.169.254/latest", "enabled": 1}}),
			self.config(endpoints={"Verify Credentials": {"method": "GET", "url": "file:///etc/passwd", "enabled": 1}}),
		):
			with self.assertRaises(PermanentError):
				self.engine.execute(cfg, "Verify Credentials", context=self.context())
		self.assertEqual(self.state.calls("GET", "/verify"), [])

	def test_unconfigured_operation(self):
		with self.assertRaises(NotSupportedError):
			self.engine.execute(self.config(), "Register Webhook", context=self.context())

	def test_logs_are_written_and_masked(self):
		auth = {"type": "OAuth2 Client Credentials", "client_id": "cid", "client_secret": "super-secret-value",
			"token_url": "/oauth/token"}
		self.engine.execute(self.config(auth), "Submit Invoice", context=self.context(key="K-L"))
		dump = json.dumps(self.logs, default=str)
		self.assertEqual([entry["operation"] for entry in self.logs], ["Authenticate", "Submit Invoice"])
		self.assertNotIn("super-secret-value", dump)
		self.assertNotIn("tok-", json.dumps([entry["request_headers"] for entry in self.logs]))
		self.assertEqual(mask({"Authorization": "Bearer abc", "x": "has abcd1234 inside"}, ["abcd1234"]),
			{"Authorization": "***", "x": "has *** inside"})


class TestConfiguredAdapter(RestEngineCase):
	def adapter(self, **rest):
		return ConfiguredRestAdapter({"name": "ASPC-TEST", "webhook_secret": None,
			"rest": {**self.config(**rest), "participant": {"participant_id": "P-77"}}})

	def test_capabilities_follow_configured_operations(self):
		adapter = self.adapter()
		self.assertTrue(adapter.supports("submit") and adapter.supports("document_pdf"))
		self.assertFalse(adapter.supports("register_webhook") or adapter.supports("incoming_invoices"))
		with self.assertRaises(NotSupportedError):
			adapter.register_webhook("https://hub.example.com/hook")

	def test_submit_status_and_documents(self):
		adapter = self.adapter()
		meta = {"transaction": "EINV-1", "idempotency_key": "EINV-1", "_canonical": INVOICE}
		result = adapter.submit_invoice("<xml/>", meta)
		self.assertEqual((result["status"], result["reference"][:4]), ("ACCEPTED", "DOC-"))
		status = adapter.get_document_status(result["reference"])
		self.assertEqual((status["fta_status"], status["delivery_status"]), ("REPORTED", "DELIVERED"))
		self.assertEqual(adapter.get_document_xml(result["reference"]), "<Invoice>mock</Invoice>")
		self.assertEqual(adapter.get_document_pdf(result["reference"])[:4], b"%PDF")

	def test_provider_refusal_is_a_rejection_not_an_error(self):
		refused = copy.deepcopy(INVOICE)
		refused["document"]["invoice_number"] = "INV-REJECT-1"
		result = self.adapter().submit_invoice("<xml/>", {"transaction": "EINV-2", "_canonical": refused})
		self.assertEqual((result["status"], result["error_code"]), ("REJECTED", "MOCK-REFUSED"))

	def test_webhook_verification_schemes(self):
		body = b'{"id": "evt_1", "type": "document.status", "data": {"document_id": "DOC-0001", "status": "delivered"}}'
		signature = hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
		self.assertTrue(verify_configured({"auth_type": "HMAC-SHA256", "secret": "s3cret", "header": "X-Sig"}, body, {"x-sig": signature}))
		self.assertFalse(verify_configured({"auth_type": "HMAC-SHA256", "secret": "s3cret", "header": "X-Sig"}, body + b" ", {"X-Sig": signature}))
		self.assertTrue(verify_configured({"auth_type": "Shared Secret", "secret": "tok", "header": "X-Token"}, body, {"X-Token": "tok"}))
		self.assertFalse(verify_configured({"auth_type": "Shared Secret", "secret": "tok", "header": "X-Token"}, body, {}))
		self.assertFalse(verify_configured({"auth_type": "HMAC-SHA256", "secret": None, "header": "X-Sig"}, body, {"X-Sig": signature}))
		# Standard Webhooks
		key = b"0123456789abcdef"
		stamp = str(int(time.time()))
		signed = base64.b64encode(hmac.new(key, b"msg_1." + stamp.encode() + b"." + body, hashlib.sha256).digest()).decode()
		headers = {"webhook-id": "msg_1", "webhook-timestamp": stamp, "webhook-signature": f"v1,{signed}"}
		config = {"auth_type": "Standard Webhooks", "secret": "whsec_" + base64.b64encode(key).decode()}
		self.assertTrue(verify_configured(config, body, headers))
		self.assertFalse(verify_configured(config, body, {**headers, "webhook-timestamp": str(int(stamp) - 4000)}))
		self.assertFalse(verify_configured(config, body + b"x", headers))

	def test_webhook_parsing(self):
		webhook = {"enabled": 1, "event_id_path": "id", "event_type_path": "type", "document_id_path": "data.document_id",
			"status_path": "data.status", "document_events": "document.received",
			"payload_mapping": '{"fta_status": "data.tax_authority_status", "delivery_status": "data.delivery_status"}'}
		adapter = self.adapter(webhook=webhook)
		parsed = adapter.process_webhook({"id": "evt_9", "type": "document.reported",
			"data": {"document_id": "DOC-0001", "tax_authority_status": "NOT_COMPLIANT"}})
		self.assertEqual((parsed["kind"], parsed["event_id"], parsed["reference"], parsed["fta_status"]),
			("status", "evt_9", "DOC-0001", "REJECTED"))
		inbound = adapter.process_webhook({"id": "evt_10", "type": "document.received", "data": {"document_id": "IN-1"}})
		self.assertEqual((inbound["kind"], inbound["reference"]), ("document", "IN-1"))


if __name__ == "__main__":
	unittest.main()
