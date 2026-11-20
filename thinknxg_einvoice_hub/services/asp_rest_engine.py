"""Configuration-driven REST engine for Accredited Service Provider APIs.

An ordinary REST-based ASP is onboarded by filling an "ASP REST API Configuration"
record; no connector code is written. This module is framework-independent: it
receives the configuration as a plain dict (see ``core.connections.rest_configuration``)
and never reads the database.

Safety properties
* only HTTPS, only hosts listed for the configuration, never private/local addresses
  (unless the deployment explicitly allows them), redirects are not followed
* connect/read timeouts and a response-size limit on every call
* mapping rules use a fixed whitelist of transformations; nothing from a
  configuration is ever evaluated or imported
* secrets are masked before anything is logged or put into an error message
"""

import base64
import hashlib
import hmac
import json
import re
import time
import uuid
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from urllib.parse import quote, urlparse

import requests

from thinknxg_einvoice_hub.exceptions import MappingError, NotSupportedError, PermanentError, TransientError
from thinknxg_einvoice_hub.http_client import assert_allowed_url
from thinknxg_einvoice_hub.utils import get_path, hook_map, load_class, set_path, to_decimal, to_iso_date

OPERATIONS = (
	"Authenticate", "Verify Credentials", "Get Participant", "Register Participant", "Validate Invoice",
	"Submit Invoice", "Submit Credit Note", "Submit Self-Billed Invoice", "Get Invoice Status",
	"Get Reporting Status", "Get Delivery Status", "Download XML", "Download PDF", "Get Incoming Invoices",
	"Register Webhook", "Get Webhook Subscription", "Custom Operation",
)
AUTH_TYPES = (
	"None", "API Key", "Bearer Token", "OAuth2 Client Credentials", "OAuth2 Authorization Code", "Basic",
	"Custom Header", "HMAC-SHA256", "JWT", "Plugin",
)
PLATFORM_FIELDS = (
	"success", "asp_document_id", "submission_reference", "submission_status", "fta_status", "fta_reference",
	"delivery_status", "delivery_reference", "error_code", "error_message", "xml_url", "pdf_url", "timestamp",
	# Peppol Message Level Status codes (AP / AB / RE); the country engine turns them into reporting / delivery
	"invoice_mls_code", "tdd_mls_code",
)
SECRET_KEYS = ("api_key", "api_secret", "client_secret", "password", "refresh_token", "static_authorization_header",
	"signing_secret")
SENSITIVE = re.compile(r"authoriz|secret|token|password|api[-_]?key|signature|credential", re.I)
RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
DEFAULT_MAX_RESPONSE_BYTES = 10 * 1024 * 1024

# provider wording -> platform status; overridable per mapping rule with a map:{...} transformation
SUBMISSION_STATES = {
	"accepted": "ACCEPTED", "success": "ACCEPTED", "ok": "ACCEPTED", "valid": "ACCEPTED", "validated": "ACCEPTED",
	"submitted": "SUBMITTED", "sent": "SUBMITTED", "received": "SUBMITTED", "queued": "PENDING",
	"pending": "PENDING", "processing": "PENDING", "in_progress": "PENDING", "delivered": "DELIVERED",
	"completed": "DELIVERED", "rejected": "REJECTED", "invalid": "REJECTED", "failed": "FAILED", "error": "FAILED",
}
FTA_STATES = {
	"pending": "PENDING", "queued": "PENDING", "processing": "PENDING", "reported": "REPORTED",
	"accepted": "REPORTED", "success": "REPORTED", "cleared": "REPORTED", "rejected": "REJECTED",
	"failed": "REJECTED", "error": "REJECTED", "reporting": "PENDING", "unresolved": "PENDING",
	"not_compliant": "REJECTED", "withdrawn": "REJECTED",
}
DELIVERY_STATES = {
	"pending": "PENDING", "queued": "PENDING", "processing": "PENDING", "sent": "PENDING",
	"delivered": "DELIVERED", "received": "DELIVERED", "success": "DELIVERED", "failed": "FAILED",
	"undeliverable": "FAILED", "rejected": "FAILED", "error": "FAILED", "sending": "PENDING",
	"retrying": "PENDING", "received_by_ap": "PENDING", "forwarded": "PENDING",
	"delivered_confirmed": "DELIVERED", "attention_required": "FAILED",
}
UAE_TAX_CODES = {"STANDARD": "S", "ZERO_RATED": "Z", "EXEMPT": "E", "OUT_OF_SCOPE": "O", "REVERSE_CHARGE": "AE",
	"MARGIN_SCHEME": "N"}


# ------------------------------------------------------------------ masking
def mask(value, secrets=()):
	"""Copy of ``value`` with credentials removed; safe to log or show."""
	if isinstance(value, dict):
		return {k: ("***" if SENSITIVE.search(str(k)) else mask(v, secrets)) for k, v in value.items()}
	if isinstance(value, (list, tuple)):
		return [mask(v, secrets) for v in value]
	if isinstance(value, str):
		for secret in secrets:
			if secret and len(secret) >= 4:
				value = value.replace(secret, "***")
		return value
	return value


def _secrets(configuration):
	auth = configuration.get("auth") or {}
	return [str(auth[k]) for k in SECRET_KEYS if auth.get(k)]


# ------------------------------------------------------------------ transformations (whitelist)
def _t_date(value, arg):
	iso = to_iso_date(value)
	return datetime.strptime(iso, "%Y-%m-%d").strftime(arg) if (iso and arg) else iso


def _t_fixed(value, arg):
	d = to_decimal(value)
	if d is None:
		return None
	return str(d.quantize(Decimal(1).scaleb(-int(arg or 2)), rounding=ROUND_HALF_UP))


def _t_map(value, arg):
	try:
		table = json.loads(arg or "{}")
	except ValueError as e:
		raise MappingError(f"map: argument is not valid JSON ({e})") from e
	lowered = {str(k).lower(): v for k, v in table.items()}
	return lowered.get(str(value).lower(), table.get("*", value))


TRANSFORMATIONS = {
	"upper": lambda v, a: str(v).upper(),
	"lower": lambda v, a: str(v).lower(),
	"strip": lambda v, a: str(v).strip(),
	"digits": lambda v, a: re.sub(r"\D", "", str(v)),
	"date": _t_date,
	"decimal": _t_fixed,
	"number": lambda v, a: (lambda d: None if d is None else float(_t_fixed(d, a or 2)))(to_decimal(v)),
	"integer": lambda v, a: (lambda d: None if d is None else int(d))(to_decimal(v)),
	"bool_yn": lambda v, a: "Y" if _truthy(v) else "N",
	"bool_10": lambda v, a: 1 if _truthy(v) else 0,
	"base64": lambda v, a: base64.b64encode((v if isinstance(v, bytes) else str(v).encode("utf-8"))).decode(),
	"map": _t_map,
	"prefix": lambda v, a: f"{a or ''}{v}",
	"suffix": lambda v, a: f"{v}{a or ''}",
	"uae_tax_code": lambda v, a: UAE_TAX_CODES.get(str(v).upper(), v),
	"json": lambda v, a: json.dumps(v, ensure_ascii=False, default=str),
}


def _truthy(value):
	return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def transformations():
	"""Built-ins plus functions registered by installed apps (``einvoice_hub_rest_transformations`` hook)."""
	table = dict(TRANSFORMATIONS)
	for name, path in hook_map("einvoice_hub_rest_transformations").items():
		table[name] = load_class(path)
	return table


def transform(value, spec, table=None):
	"""Apply ``name`` / ``name:arg`` steps separated by ``|``. ``const:x`` works without an input value."""
	table = table or TRANSFORMATIONS
	for step in [s.strip() for s in str(spec or "").split("|") if s.strip() and s.strip().lower() != "none"]:
		name, _, arg = step.partition(":")
		name = name.strip().lower()
		if name == "const":
			value = arg
			continue
		if name not in table:
			raise MappingError(f"Transformation '{name}' is not registered")
		if value is None:
			continue
		value = table[name](value, arg)
	return value


def convert(value, data_type):
	if value is None:
		return None
	kind = (data_type or "String").strip()
	if kind == "String":
		return value if isinstance(value, str) else (json.dumps(value) if isinstance(value, (dict, list)) else str(value))
	if kind == "Integer":
		d = to_decimal(value)
		return int(d) if d is not None else None
	if kind == "Decimal":
		d = to_decimal(value)
		return float(d) if d is not None else None
	if kind == "Boolean":
		return value if isinstance(value, bool) else _truthy(value)
	if kind == "Date":
		return to_iso_date(value)
	if kind == "DateTime":
		return value.isoformat() if isinstance(value, datetime) else str(value)
	return value  # JSON / Raw


def _condition(expr, context):
	"""``path == value``, ``path != value`` or ``path`` (exists). No expression evaluation."""
	expr = (expr or "").strip()
	if not expr:
		return True
	for op in ("==", "!="):
		if op in expr:
			path, _, expected = expr.partition(op)
			actual = get_path(context, path.strip())
			same = str(actual if actual is not None else "").strip() == expected.strip().strip("'\"")
			return same if op == "==" else not same
	return get_path(context, expr) not in (None, "", [], {})


def dynamic_value(name, context):
	name = (name or "").strip().lstrip("$").lower()
	now = datetime.now(timezone.utc)
	if name == "now":
		return now.strftime("%Y-%m-%dT%H:%M:%SZ")
	if name == "today":
		return now.strftime("%Y-%m-%d")
	if name == "timestamp":
		return str(int(now.timestamp()))
	if name == "uuid":
		return str(uuid.uuid4())
	value = get_path(context, name)
	if value is None:
		raise MappingError(f"Dynamic value '{name}' is not available")
	return value


def apply_request_mappings(rules, operation, context, table=None):
	"""Build a request body from mapping rules. Returns ``None`` when no rule applies to the operation."""
	rules = [r for r in rules or [] if r.get("enabled", 1) and (r.get("operation") or operation) == operation]
	if not rules:
		return None
	body = {}

	def value_of(rule, scope, path):
		if path.startswith("$"):
			raw = dynamic_value(path, context)
		else:
			raw = get_path(scope, path) if path else None
		val = transform(raw, rule.get("transformation"), table)
		if val in (None, "") and rule.get("default") not in (None, ""):
			val = rule["default"]
		val = convert(val, rule.get("data_type"))
		if val in (None, "") and rule.get("required"):
			raise MappingError(f"{operation}: required source field '{rule.get('source')}' is missing")
		return val

	for rule in rules:
		if not _condition(rule.get("condition"), context):
			continue
		source, target = (rule.get("source") or "").strip(), (rule.get("target") or "").strip()
		if "[]" not in target:
			val = value_of(rule, context, source)
			if val not in (None, ""):
				set_path(body, target, val)
			continue
		t_head, _, t_tail = target.partition("[]")
		t_head, t_tail = t_head.strip("."), t_tail.strip(".")
		if "[]" not in source:
			raise MappingError(f"{operation}: array target '{target}' needs an array source such as invoice.lines[].x")
		s_head, _, s_tail = source.partition("[]")
		items = get_path(context, s_head.strip(".")) or []
		rows = get_path(body, t_head)
		if not isinstance(rows, list):
			rows = []
			set_path(body, t_head, rows)
		for i, item in enumerate(items):
			while len(rows) <= i:
				rows.append({})
			val = value_of(rule, item, s_tail.strip(".")) if s_tail.strip(".") else item
			if val in (None, ""):
				continue
			if t_tail:
				set_path(rows[i], t_tail, val)
			else:
				rows[i] = val
	return body


def _state(value, table):
	if value in (None, ""):
		return None
	text = str(value).strip()
	if text.upper() in set(table.values()):
		return text.upper()
	return table.get(text.lower().replace(" ", "_"), text.upper())


# ------------------------------------------------------------------ engine
class MemoryTokenStore:
	def __init__(self):
		self._data = {}

	def get(self, key):
		value, expires = self._data.get(key, (None, 0))
		return value if time.time() < expires else None

	def set(self, key, value, ttl):
		self._data[key] = (value, time.time() + ttl)

	def delete(self, key):
		self._data.pop(key, None)


class ASPRestEngine:
	def __init__(self, token_store=None, logger=None, sleep=time.sleep):
		self.tokens = token_store or MemoryTokenStore()
		self.logger = logger
		self.sleep = sleep

	# -- configuration helpers -----------------------------------------
	@staticmethod
	def endpoint(configuration, operation):
		ep = (configuration.get("endpoints") or {}).get(operation)
		if not ep or not ep.get("enabled", 1) or not (ep.get("url") or "").strip():
			raise NotSupportedError(
				f"Operation '{operation}' is not configured for {configuration.get('name') or 'this ASP'}"
			)
		return ep

	@staticmethod
	def has_operation(configuration, operation):
		ep = (configuration.get("endpoints") or {}).get(operation)
		return bool(ep and ep.get("enabled", 1) and (ep.get("url") or "").strip())

	def _url(self, configuration, relative, path_params=None):
		for key, val in (path_params or {}).items():
			relative = relative.replace("{" + key + "}", quote(str(val), safe=""))
		missing = re.findall(r"\{(\w+)\}", relative)
		if missing:
			raise PermanentError(f"URL parameter(s) {', '.join(missing)} were not supplied for '{relative}'")
		if relative.startswith(("http://", "https://")):
			url = relative
		else:
			url = f"{(configuration.get('base_url') or '').rstrip('/')}/{relative.lstrip('/')}"
		self._check_url(configuration, url)
		return url

	@staticmethod
	def _check_url(configuration, url):
		parsed = urlparse(url)
		if parsed.scheme != "https" and not configuration.get("allow_insecure"):
			raise PermanentError(f"Only HTTPS endpoints are allowed ({parsed.scheme}://{parsed.hostname})")
		allowed = {h.lower() for h in configuration.get("allowed_hosts") or []}
		if (parsed.hostname or "").lower() not in allowed:
			raise PermanentError(f"Host '{parsed.hostname}' is not an approved host for this ASP configuration")
		assert_allowed_url(url, bool(configuration.get("allow_private_hosts")))

	def _token_key(self, configuration):
		auth = configuration.get("auth") or {}
		identity = "|".join(str(auth.get(k) or "") for k in ("client_id", "api_key", "username"))
		return "eih_token:" + hashlib.sha256(
			f"{configuration.get('code')}|{configuration.get('base_url')}|{identity}".encode()
		).hexdigest()

	# -- authentication ----------------------------------------------------
	def authenticate(self, configuration):
		"""Return authentication headers for the configuration (fetching a token when needed)."""
		auth = configuration.get("auth") or {}
		kind = auth.get("type") or "None"
		headers = {}
		if kind == "API Key":
			headers[auth.get("api_key_header") or "X-API-Key"] = f"{auth.get('api_key_prefix') or ''}{auth.get('api_key') or ''}"
		elif kind == "Bearer Token":
			if auth.get("static_authorization_header"):
				headers["Authorization"] = auth["static_authorization_header"]
			else:
				headers["Authorization"] = f"Bearer {auth.get('api_secret') or auth.get('api_key') or ''}"
		elif kind in ("OAuth2 Client Credentials", "OAuth2 Authorization Code"):
			token = self.tokens.get(self._token_key(configuration)) or self.refresh_token(configuration)
			headers["Authorization"] = f"Bearer {token}"
		elif kind == "Basic":
			raw = f"{auth.get('username') or ''}:{auth.get('password') or ''}".encode()
			headers["Authorization"] = "Basic " + base64.b64encode(raw).decode()
		elif kind == "JWT":
			headers["Authorization"] = f"Bearer {self._jwt(auth)}"
		elif kind not in ("None", "Custom Header", "HMAC-SHA256", "Plugin"):
			raise PermanentError(f"Unsupported authentication type '{kind}'")
		if auth.get("static_authorization_header") and kind in ("Custom Header", "HMAC-SHA256"):
			headers["Authorization"] = auth["static_authorization_header"]
		values = {k: auth.get(k) or "" for k in ("api_key", "api_secret", "client_id", "client_secret", "username", "password")}
		for name, template in (auth.get("custom_headers") or {}).items():
			headers[name] = re.sub(r"\{(\w+)\}", lambda m: str(values.get(m.group(1), m.group(0))), str(template))
		return headers

	@staticmethod
	def _jwt(auth):
		"""HS256 token signed with the API secret. Other algorithms need an authentication plugin."""
		def b64(data):
			return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

		now = int(time.time())
		claims = {"iss": auth.get("client_id") or auth.get("api_key"), "iat": now,
			"exp": now + int(auth.get("token_expiry") or 300)}
		claims.update(auth.get("jwt_claims") or {})
		signing = b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode()) + "." + b64(
			json.dumps(claims, separators=(",", ":")).encode())
		signature = hmac.new(str(auth.get("api_secret") or "").encode(), signing.encode(), hashlib.sha256).digest()
		return f"{signing}.{b64(signature)}"

	def refresh_token(self, configuration):
		"""Obtain a new access token and cache it until shortly before it expires."""
		auth = configuration.get("auth") or {}
		kind = auth.get("type")
		if kind == "OAuth2 Authorization Code":
			if not auth.get("refresh_token"):
				raise PermanentError("No refresh token is stored; complete the provider's authorization step first")
			data = {"grant_type": "refresh_token", "refresh_token": auth["refresh_token"]}
			url = auth.get("refresh_token_url") or auth.get("token_url")
		else:
			data = {"grant_type": "client_credentials"}
			url = auth.get("token_url")
		data.update({"client_id": auth.get("client_id"), "client_secret": auth.get("client_secret")})
		if auth.get("scope"):
			data["scope"] = auth["scope"]
		if not url:
			raise PermanentError("Token URL is not configured")
		url = self._url(configuration, url)
		as_json = "json" in (auth.get("token_content_type") or "").lower()
		response = self._send(configuration, "Authenticate", auth.get("token_method") or "POST", url, headers={},
			timeout=30, **({"json": data} if as_json else {"data": data}))
		if response["status"] >= 400:
			self.handle_error(configuration, "Authenticate", response)
		body = response["data"] if isinstance(response["data"], dict) else {}
		token = get_path(body, auth.get("token_response_path") or "access_token")
		if not token:
			raise PermanentError("Token endpoint did not return an access token")
		ttl = int(to_decimal(get_path(body, auth.get("expiry_response_path") or "expires_in"),
			Decimal(str(auth.get("token_expiry") or 300))))
		self.tokens.set(self._token_key(configuration), token, max(ttl - 30, 30))
		return token

	# -- request construction ----------------------------------------------
	def build_headers(self, configuration, operation, context=None, body=b"", method="GET", url=""):
		ep = (configuration.get("endpoints") or {}).get(operation) or {}
		context = context or {}
		headers = {"Accept": ep.get("response_content_type") or "application/json"}
		for row in configuration.get("headers") or []:
			if not row.get("enabled", 1) or not row.get("name"):
				continue
			if (row.get("value_type") or "Static") == "Dynamic":
				headers[row["name"]] = str(dynamic_value(row.get("dynamic_value") or row.get("value"), context))
			else:
				headers[row["name"]] = str(row.get("value") or "")
		auth = configuration.get("auth") or {}
		if ep.get("auth_required", 1):
			kind = auth.get("type") or "None"
			if kind == "Plugin":
				plugin = hook_map("einvoice_hub_rest_auth_plugins").get(auth.get("plugin") or "")
				if not plugin:
					raise PermanentError(f"Authentication plugin '{auth.get('plugin')}' is not installed")
				headers.update(load_class(plugin)(configuration=configuration, operation=operation, method=method,
					url=url, body=body) or {})
			else:
				headers.update(self.authenticate(configuration))
			if kind == "HMAC-SHA256":
				stamp = str(int(time.time()))
				template = auth.get("hmac_template") or "{timestamp}.{method}.{path}.{body}"
				message = (template.replace("{timestamp}", stamp).replace("{method}", method.upper())
					.replace("{path}", urlparse(url).path).replace("{body}", body.decode("utf-8") if body else ""))
				digest = hmac.new(str(auth.get("api_secret") or "").encode(), message.encode(), hashlib.sha256).digest()
				signature = base64.b64encode(digest).decode() if auth.get("hmac_encoding") == "base64" else digest.hex()
				headers[auth.get("hmac_signature_header") or "X-Signature"] = signature
				headers[auth.get("hmac_timestamp_header") or "X-Timestamp"] = stamp
				if auth.get("api_key"):
					headers[auth.get("api_key_header") or "X-API-Key"] = auth["api_key"]
		if ep.get("idempotency") and context.get("idempotency_key"):
			headers[ep.get("idempotency_header") or "Idempotency-Key"] = str(context["idempotency_key"])
		return headers

	def build_request(self, configuration, operation, payload=None, context=None, path_params=None):
		ep = self.endpoint(configuration, operation)
		method = (ep.get("method") or "GET").upper()
		url = self._url(configuration, ep["url"], path_params)
		context = dict(context or {})
		mapped = apply_request_mappings(configuration.get("request_mappings"), operation, context, transformations())
		content_type = ep.get("request_content_type") or "application/json"
		body, params = b"", None
		source = mapped if mapped is not None else payload
		if method in ("GET", "DELETE", "HEAD"):
			params = source if isinstance(source, dict) else None
		elif source is not None:
			if isinstance(source, (dict, list)):
				body = json.dumps(source, ensure_ascii=False, default=str).encode("utf-8")
			else:
				body = source if isinstance(source, bytes) else str(source).encode("utf-8")
		headers = self.build_headers(configuration, operation, context, body, method, url)
		if body:
			headers["Content-Type"] = content_type
		return {"method": method, "url": url, "headers": headers, "body": body, "params": params,
			"timeout": int(ep.get("timeout") or 30), "endpoint": ep}

	# -- transport ---------------------------------------------------------
	def _send(self, configuration, operation, method, url, headers, timeout=30, **kw):
		limit = int(configuration.get("max_response_bytes") or DEFAULT_MAX_RESPONSE_BYTES)
		started = time.time()
		try:
			resp = requests.request(method, url, headers=headers, timeout=(10, timeout), stream=True,
				verify=bool(configuration.get("verify_ssl", True)), allow_redirects=False, **kw)
			content = resp.raw.read(limit + 1, decode_content=True)
			resp.close()
		except (requests.ConnectionError, requests.Timeout) as e:
			self._log(configuration, operation, method, url, None, started, error=f"{type(e).__name__}")
			raise TransientError(f"{operation}: could not reach {urlparse(url).hostname} ({type(e).__name__})") from e
		except requests.RequestException as e:
			self._log(configuration, operation, method, url, None, started, error=type(e).__name__)
			raise PermanentError(f"{operation}: request failed ({type(e).__name__})") from e
		if len(content) > limit:
			raise PermanentError(f"{operation}: response exceeds the {limit} byte limit")
		response = {"status": resp.status_code, "headers": dict(resp.headers), "content": content, "data": None}
		response["data"] = self.parse_response(configuration, operation, response)
		self._log(configuration, operation, method, url, response, started, request_headers=headers,
			request_body=kw.get("data") or kw.get("json"))
		return response

	def _log(self, configuration, operation, method, url, response, started, error=None, request_headers=None,
			request_body=None):
		if not self.logger:
			return
		secrets = _secrets(configuration)
		body = request_body
		if isinstance(body, bytes):
			body = body[:20000].decode("utf-8", errors="replace")
		data = response["data"] if response else None
		if isinstance(data, bytes):
			data = f"<{len(data)} bytes>"
		try:
			self.logger({
				"operation": operation, "http_method": method, "url": mask(url.split("?")[0], secrets),
				"http_status": response["status"] if response else None,
				"duration_ms": int((time.time() - started) * 1000),
				"result": "Success" if (response and response["status"] < 400) else "Failure",
				"error": error, "request_headers": mask(request_headers or {}, secrets),
				"request": mask(_maybe_json(body), secrets), "response": mask(data, secrets),
			})
		except Exception:
			pass  # logging must never break a transmission

	def parse_response(self, configuration, operation, response):
		content = response.get("content") or b""
		kind = (response.get("headers") or {}).get("Content-Type", "").lower()
		if not content:
			return {}
		if "json" in kind or content[:1] in (b"{", b"["):
			try:
				return json.loads(content.decode("utf-8"))
			except (ValueError, UnicodeDecodeError):
				if "json" in kind:
					raise PermanentError(f"{operation}: provider returned invalid JSON") from None
		if "pdf" in kind or "octet-stream" in kind or content[:4] == b"%PDF":
			return content
		try:
			return content.decode("utf-8")
		except UnicodeDecodeError:
			return content

	def map_response(self, configuration, response, operation=None):
		"""Provider response -> platform fields (see ``PLATFORM_FIELDS``)."""
		data = response["data"] if isinstance(response, dict) and "data" in response else response
		mapped = {}
		table = transformations()
		for rule in configuration.get("response_mappings") or []:
			if not rule.get("enabled", 1) or (rule.get("operation") and operation and rule["operation"] != operation):
				continue
			value = get_path(data, rule.get("path")) if isinstance(data, (dict, list)) else None
			value = transform(value, rule.get("transformation"), table)
			if value in (None, "") and rule.get("default") not in (None, ""):
				value = rule["default"]
			if value in (None, ""):
				if rule.get("required"):
					raise PermanentError(f"Provider response is missing required field '{rule.get('path')}'")
				continue
			mapped[rule["target"]] = value
		if "success" in mapped and not isinstance(mapped["success"], bool):
			mapped["success"] = _truthy(mapped["success"])
		for field, table_ in (("submission_status", SUBMISSION_STATES), ("fta_status", FTA_STATES),
				("delivery_status", DELIVERY_STATES)):
			if field in mapped:
				mapped[field] = _state(mapped[field], table_)
		for field in ("asp_document_id", "submission_reference", "fta_reference", "delivery_reference", "error_code"):
			if field in mapped:
				mapped[field] = str(mapped[field])
		if isinstance(mapped.get("error_message"), (dict, list)):
			mapped["error_message"] = json.dumps(mapped["error_message"], ensure_ascii=False)[:2000]
		return mapped

	def handle_error(self, configuration, operation, response):
		"""Raise the right exception for an HTTP error response. Messages never contain credentials."""
		status = response["status"]
		try:
			mapped = self.map_response(configuration, response, operation)
		except PermanentError:
			mapped = {}
		detail = mapped.get("error_message")
		if not detail:
			data = response.get("data")
			detail = json.dumps(data)[:500] if isinstance(data, (dict, list)) else str(data or "")[:500]
		code = f" [{mapped['error_code']}]" if mapped.get("error_code") else ""
		message = mask(f"{operation}: HTTP {status}{code} {detail}".strip(), _secrets(configuration))
		if status in RETRYABLE_STATUS:
			raise TransientError(message)
		raise PermanentError(message)

	def execute(self, configuration, operation, payload=None, context=None, path_params=None):
		"""Run one configured operation. Returns ``{"status", "headers", "data", "content", "mapped"}``."""
		request = self.build_request(configuration, operation, payload, context, path_params)
		ep, method = request["endpoint"], request["method"]
		safe_to_repeat = method in ("GET", "HEAD") or bool(ep.get("idempotency") and (context or {}).get("idempotency_key"))
		attempts = 1 + (int(ep.get("max_retries") or 0) if (ep.get("retry") and safe_to_repeat) else 0)
		backoff = float(configuration.get("retry_backoff_seconds", 1))
		refreshed = False
		attempt = 0
		while True:
			attempt += 1
			kw = {"params": request["params"]} if request["params"] else {}
			if request["body"]:
				kw["data"] = request["body"]
			try:
				response = self._send(configuration, operation, method, request["url"], request["headers"],
					request["timeout"], **kw)
			except TransientError:
				if attempt >= attempts:
					raise
				self.sleep(min(backoff * (2 ** (attempt - 1)), 30))
				continue
			status = response["status"]
			auth_kind = (configuration.get("auth") or {}).get("type") or ""
			if status == 401 and auth_kind.startswith("OAuth2") and not refreshed and ep.get("auth_required", 1):
				refreshed = True
				self.tokens.delete(self._token_key(configuration))
				request = self.build_request(configuration, operation, payload, context, path_params)
				continue
			if status in RETRYABLE_STATUS and attempt < attempts:
				retry_after = to_decimal(response["headers"].get("Retry-After"))
				self.sleep(min(float(retry_after) if retry_after is not None else backoff * (2 ** (attempt - 1)), 30))
				continue
			if 300 <= status < 400:
				raise PermanentError(f"{operation}: provider answered with a redirect (HTTP {status}), which is not followed")
			if status >= 400:
				self.handle_error(configuration, operation, response)
			response["mapped"] = self.map_response(configuration, response, operation)
			return response


def _maybe_json(body):
	if isinstance(body, str) and body[:1] in ("{", "["):
		try:
			return json.loads(body)
		except ValueError:
			return body
	return body
