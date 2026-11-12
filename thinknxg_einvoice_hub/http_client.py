"""Small HTTP client shared by ERP connectors and ASP adapters.

Translates transport problems into ``TransientError`` / ``PermanentError`` so the
retry engine can decide what to do, and refuses private-network targets unless
the deployment explicitly allows them (protects shared deployments from
server-side request forgery through tenant-supplied URLs).
"""

import base64
import ipaddress
import socket
import time
from urllib.parse import urlparse

import requests

from thinknxg_einvoice_hub.exceptions import PermanentError, TransientError

RETRYABLE_STATUS = {408, 425, 429}


def assert_allowed_url(url, allow_private=False):
	parsed = urlparse(url)
	if parsed.scheme not in ("http", "https") or not parsed.hostname:
		raise PermanentError(f"Unsupported URL: {url}")
	if allow_private:
		return
	try:
		infos = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
	except socket.gaierror as e:
		raise TransientError(f"Cannot resolve host {parsed.hostname}: {e}") from e
	for info in infos:
		ip = ipaddress.ip_address(info[4][0])
		if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
			raise PermanentError(
				f"Host {parsed.hostname} resolves to a private or local address. "
				"Enable 'Allow Connections to Private Network Hosts' in E-Invoice Hub Settings to permit this."
			)


class HttpClient:
	def __init__(self, cfg):
		self.cfg = cfg
		self.extra = cfg.get("extra") or {}
		self.base_url = (cfg.get("base_url") or "").rstrip("/")
		self.timeout = int(cfg.get("timeout") or 30)
		self.verify = bool(cfg.get("verify_ssl", True))
		self.allow_private = bool(cfg.get("allow_private_hosts"))
		self._token = None
		self._token_expiry = 0

	# -- authentication -------------------------------------------------
	def auth_headers(self):
		kind = self.cfg.get("auth_type") or "None"
		if kind == "API Key and Secret":
			scheme = self.extra.get("auth_scheme", "token")
			return {"Authorization": f"{scheme} {self.cfg.get('api_key')}:{self.cfg.get('api_secret')}"}
		if kind == "Basic":
			raw = f"{self.cfg.get('username')}:{self.cfg.get('password')}".encode()
			return {"Authorization": "Basic " + base64.b64encode(raw).decode()}
		if kind == "Bearer Token":
			return {"Authorization": f"Bearer {self.cfg.get('api_secret')}"}
		if kind == "OAuth2 Client Credentials":
			return {"Authorization": f"Bearer {self._oauth_token()}"}
		return {}

	def _oauth_token(self):
		if self._token and time.time() < self._token_expiry - 30:
			return self._token
		data = {
			"grant_type": "client_credentials",
			"client_id": self.cfg.get("client_id"),
			"client_secret": self.cfg.get("client_secret"),
		}
		if self.cfg.get("scope"):
			data["scope"] = self.cfg["scope"]
		body = self._send("POST", self.cfg.get("token_url"), data=data, auth=False).json()
		self._token = body.get("access_token")
		if not self._token:
			raise PermanentError("OAuth token endpoint did not return an access_token")
		self._token_expiry = time.time() + int(body.get("expires_in") or 300)
		return self._token

	# -- requests ---------------------------------------------------------
	def url(self, path):
		if str(path).startswith(("http://", "https://")):
			return path
		return f"{self.base_url}/{str(path).lstrip('/')}"

	def _send(self, method, path, auth=True, **kw):
		url = self.url(path)
		assert_allowed_url(url, self.allow_private)
		headers = dict(self.auth_headers() if auth else {})
		headers.update(kw.pop("headers", None) or {})
		try:
			resp = requests.request(
				method, url, headers=headers, timeout=self.timeout, verify=self.verify, allow_redirects=False, **kw
			)
		except (requests.ConnectionError, requests.Timeout) as e:
			raise TransientError(f"{method} {url} failed: {e}") from e
		except requests.RequestException as e:
			raise PermanentError(f"{method} {url} failed: {e}") from e
		if resp.status_code in RETRYABLE_STATUS or resp.status_code >= 500:
			raise TransientError(f"{method} {url} returned HTTP {resp.status_code}: {resp.text[:500]}")
		if resp.status_code >= 400:
			raise PermanentError(f"{method} {url} returned HTTP {resp.status_code}: {resp.text[:500]}")
		if 300 <= resp.status_code < 400:
			raise PermanentError(f"{method} {url} returned an unexpected redirect (HTTP {resp.status_code})")
		return resp

	def request(self, method, path, **kw):
		return self._send(method, path, **kw)

	def json(self, method, path, **kw):
		resp = self._send(method, path, **kw)
		if not resp.content:
			return {}
		try:
			return resp.json()
		except ValueError as e:
			raise PermanentError(f"{method} {self.url(path)} did not return JSON") from e
