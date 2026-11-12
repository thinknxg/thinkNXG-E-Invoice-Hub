"""MOCK ASP API used only by the automated tests and local sandbox trials.

Everything here is invented for testing the hub's REST engine. It does not describe the API of
Microvista, Wafeq or any other real provider.

Run standalone:  python -m thinknxg_einvoice_hub.tests.mock_asp 8765
"""

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VALID_TOKENS = ("static-token",)


def _minimal_pdf():
	"""A tiny but structurally valid one-page PDF."""
	objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
		b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>"]
	out, offsets = b"%PDF-1.4\n", []
	for number, body in enumerate(objects, 1):
		offsets.append(len(out))
		out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
	xref = len(out)
	out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
	out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
	out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
	return out


MOCK_PDF = _minimal_pdf()


class MockState:
	def __init__(self):
		self.requests = []      # (method, path, headers, body)
		self.documents = {}     # idempotency key or number -> document id
		self.tokens_issued = 0
		self.fail_once = set()
		self.expire_next_token = False
		self.status_overrides = {}

	def calls(self, method, path):
		return [r for r in self.requests if r[0] == method and r[1].split("?")[0] == path]


def make_handler(state):
	class Handler(BaseHTTPRequestHandler):
		def log_message(self, *args):
			pass

		def _send(self, status, body=None, content_type="application/json", headers=None):
			raw = body if isinstance(body, bytes) else json.dumps(body if body is not None else {}).encode()
			self.send_response(status)
			self.send_header("Content-Type", content_type)
			self.send_header("Content-Length", str(len(raw)))
			for key, value in (headers or {}).items():
				self.send_header(key, value)
			self.end_headers()
			self.wfile.write(raw)

		def _authorised(self):
			auth = self.headers.get("Authorization", "")
			if auth.startswith("Bearer "):
				token = auth[7:]
				if token.count(".") == 2:  # JWT: accepted here, verified in the test itself
					return True
				if state.expire_next_token and token.startswith("tok-"):
					state.expire_next_token = False
					return False
				return token in VALID_TOKENS or token.startswith("tok-")
			if auth.startswith("Basic ") or auth.startswith("Api-Key "):
				return True
			return any(self.headers.get(h) for h in ("X-API-Key", "X-Custom-Auth", "X-Signature"))

		def _handle(self, method):
			length = int(self.headers.get("Content-Length") or 0)
			body = self.rfile.read(length) if length else b""
			path = self.path.split("?")[0]
			state.requests.append((method, self.path, dict(self.headers), body))

			if path == "/oauth/token":
				state.tokens_issued += 1
				return self._send(200, {"access_token": f"tok-{state.tokens_issued}", "expires_in": 3600})
			if path == "/redirect":
				return self._send(302, {}, headers={"Location": "https://example.org/elsewhere"})
			if path == "/badjson":
				return self._send(200, b"{not json", "application/json")
			if path == "/big":
				return self._send(200, b"x" * 200000, "text/plain")
			if path == "/slow":
				time.sleep(3)
				return self._send(200, {"ok": True})
			if path == "/ratelimit":
				if "ratelimit" not in state.fail_once:
					state.fail_once.add("ratelimit")
					return self._send(429, {"error": "slow down"}, headers={"Retry-After": "0"})
				return self._send(200, {"ok": True})
			if not self._authorised():
				return self._send(401, {"error": "unauthorised", "code": "AUTH"})
			if path == "/verify":
				return self._send(200, {"ok": True, "participant": "0235:1000000000"})
			if path == "/participants/0235:1002345678":
				return self._send(200, {"id": "0235:1002345678", "registered": True})
			if path in ("/invoices", "/credit-notes") and method == "POST":
				data = json.loads(body or b"{}") if body[:1] in (b"{", b"[") else {"raw": body.decode()}
				number = str(data.get("invoice_number") or data.get("number") or "")
				if "FLAKY" in number and number not in state.fail_once:
					state.fail_once.add(number)
					return self._send(503, {"error": "temporarily unavailable"})
				if "REJECT" in number:
					return self._send(200, {"success": False, "status": "refused", "error": "Mock: document refused",
						"code": "MOCK-REFUSED"})
				key = self.headers.get("Idempotency-Key") or number
				if key not in state.documents:
					state.documents[key] = f"DOC-{len(state.documents) + 1:04d}"
				return self._send(202, {"document_id": state.documents[key], "status": "queued",
					"kind": "credit_note" if path == "/credit-notes" else "invoice"})
			if path == "/invoices/validate":
				return self._send(200, {"valid": True, "errors": []})
			if path.startswith("/invoices/") and path.endswith("/xml"):
				return self._send(200, b"<Invoice>mock</Invoice>", "application/xml")
			if path.startswith("/invoices/") and path.endswith("/pdf"):
				return self._send(200, MOCK_PDF, "application/pdf")
			if path.startswith("/invoices/"):
				doc_id = path.rsplit("/", 1)[-1]
				return self._send(200, {"id": doc_id, **state.status_overrides.get(doc_id,
					{"tdd_status": "reported", "delivery_status": "delivered_confirmed"})})
			if path == "/inbox":
				return self._send(200, {"data": []})
			if path == "/webhooks":
				return self._send(201, {"subscription": "sub-1"})
			return self._send(404, {"error": "not found"})

		def do_GET(self):
			self._handle("GET")

		def do_POST(self):
			self._handle("POST")

	return Handler


def start(port=0):
	state = MockState()
	server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(state))
	threading.Thread(target=server.serve_forever, daemon=True).start()
	return server, state, f"http://127.0.0.1:{server.server_address[1]}"


if __name__ == "__main__":
	srv, _, url = start(int(sys.argv[1]) if len(sys.argv) > 1 else 8765)
	print(f"MOCK ASP listening on {url}", flush=True)
	threading.Event().wait()
