"""Webhook authentication helpers (framework-independent).

Supported schemes: HMAC-SHA256 over the raw body (hex or base64), Standard Webhooks,
a shared secret sent in a header, and HS256 JWTs. The header may not be ``Authorization``: the
framework treats that header as its own login credential and rejects the request
before it reaches the hub.
"""

import base64
import hashlib
import hmac
import json
import time

SIGNATURE_HEADERS = ("X-EIH-Signature", "X-Hub-Signature-256", "X-Signature")
BASE64_SIGNATURE_HEADERS = ("X-Frappe-Webhook-Signature",)


def _header(headers, name):
	if not name:
		return None
	for key, value in headers.items():
		if key.lower() == name.lower():
			return value
	return None


def _clean(value):
	value = (value or "").strip()
	return value.split("=", 1)[1] if value.lower().startswith("sha256=") else value


def verify_signature(secret, body, headers):
	"""Default scheme: HMAC-SHA256 of the raw body in one of the well-known headers."""
	if not secret:
		return False
	digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
	for name in SIGNATURE_HEADERS:
		given = _header(headers, name)
		if given:
			return hmac.compare_digest(digest.hex(), _clean(given).lower())
	for name in BASE64_SIGNATURE_HEADERS:
		given = _header(headers, name)
		if given:
			return hmac.compare_digest(base64.b64encode(digest).decode(), given.strip())
	return False


def verify_jwt_hs256(token, secret, leeway=60):
	try:
		head, payload, signature = token.split(".")
		pad = lambda s: s + "=" * (-len(s) % 4)
		if json.loads(base64.urlsafe_b64decode(pad(head))).get("alg") != "HS256":
			return False
		expected = hmac.new(secret.encode(), f"{head}.{payload}".encode(), hashlib.sha256).digest()
		if not hmac.compare_digest(expected, base64.urlsafe_b64decode(pad(signature))):
			return False
		claims = json.loads(base64.urlsafe_b64decode(pad(payload)))
		return not claims.get("exp") or float(claims["exp"]) + leeway >= time.time()
	except Exception:
		return False


def verify_standard_webhooks(secret, body, headers, tolerance=300):
	"""Standard Webhooks (standardwebhooks.com): HMAC-SHA256 over ``id.timestamp.body``, base64, ``v1,`` prefix."""
	msg_id, stamp, given = (_header(headers, n) for n in ("webhook-id", "webhook-timestamp", "webhook-signature"))
	if not (secret and msg_id and stamp and given):
		return False
	try:
		if abs(time.time() - int(stamp)) > tolerance:
			return False
		key = base64.b64decode(secret[6:]) if secret.startswith("whsec_") else secret.encode("utf-8")
	except (ValueError, TypeError):
		return False
	signed = msg_id.encode() + b"." + stamp.encode() + b"." + body
	expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
	for part in given.split():
		version, _, signature = part.partition(",")
		if version == "v1" and hmac.compare_digest(expected, signature):
			return True
	return False


def verify_configured(config, body, headers):
	"""Verify a webhook against an ASP REST webhook configuration dict."""
	config = config or {}
	kind = config.get("auth_type") or "HMAC-SHA256"
	secret = config.get("secret")
	given = _header(headers, config.get("header"))
	if kind == "None":
		return bool(config.get("allow_unsigned"))
	if not secret:
		return False
	if kind == "HMAC-SHA256":
		if not config.get("header"):
			return verify_signature(secret, body, headers)
		if not given:
			return False
		digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
		given = _clean(given)
		return hmac.compare_digest(digest.hex(), given.lower()) or hmac.compare_digest(
			base64.b64encode(digest).decode(), given)
	if kind == "Standard Webhooks":
		return verify_standard_webhooks(secret, body, headers)
	if kind == "Shared Secret":
		return bool(given) and hmac.compare_digest(secret, given.strip())
	if kind == "JWT":
		token = (given or "").strip()
		token = token[7:] if token.lower().startswith("bearer ") else token
		return bool(token) and verify_jwt_hs256(token, secret)
	return False
