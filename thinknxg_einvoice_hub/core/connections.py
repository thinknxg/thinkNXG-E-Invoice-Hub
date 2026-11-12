"""Turn ERP / ASP Connection documents into plain, decrypted config dicts.

Connectors never see documents or the database; they only get these dicts.
"""

import frappe

from thinknxg_einvoice_hub.utils import loads

PLAIN_FIELDS = ("name", "tenant", "base_url", "auth_type", "api_key", "username", "token_url", "client_id",
	"scope", "timeout", "environment", "payload_format")
SECRET_FIELDS = ("api_secret", "password", "client_secret", "webhook_secret")


def connection_config(doc):
	cfg = {field: doc.get(field) for field in PLAIN_FIELDS}
	for field in SECRET_FIELDS:
		cfg[field] = doc.get_password(field, raise_exception=False) if doc.get(field) else None
	cfg["verify_ssl"] = bool(doc.get("verify_ssl"))
	cfg["extra"] = loads(doc.get("extra_config"), {}) or {}
	cfg["allow_private_hosts"] = bool(
		frappe.db.get_single_value("E-Invoice Hub Settings", "allow_private_hosts")
	)
	if doc.doctype == "ASP Connection":
		asp_runtime(cfg, doc)
	return cfg


def mapping_config(name):
	if not name:
		return None
	doc = frappe.get_cached_doc("Mapping Configuration", name)
	if not doc.enabled:
		return None
	return {
		"line_source_path": doc.line_source_path,
		"defaults": loads(doc.defaults, {}) or {},
		"rules": [
			{
				"scope": row.scope,
				"source_path": row.source_path,
				"canonical_path": row.canonical_path,
				"transform": row.transform,
				"transform_arg": row.transform_arg,
				"default_value": row.default_value,
				"required": row.required,
			}
			for row in doc.rules
		],
	}


# ---------------------------------------------------------------------- ASP REST configuration
REST_AUTH_FIELDS = ("api_key_header", "api_key_prefix", "client_id", "username", "token_url", "token_method",
	"token_expiry", "refresh_token_url", "token_response_path", "expiry_response_path", "hmac_signature_header",
	"hmac_timestamp_header", "hmac_template", "hmac_encoding")
REST_AUTH_SECRETS = ("api_key", "api_secret", "client_secret", "password", "refresh_token", "static_authorization_header")
# credentials entered on the ASP Connection override the ones on the configuration
CONNECTION_OVERRIDES = {"api_key": "api_key", "api_secret": "api_secret", "username": "username",
	"password": "password", "client_id": "client_id", "client_secret": "client_secret", "token_url": "token_url",
	"scope": "scope"}


class CacheTokenStore:
	"""Access tokens live in the site cache only, never in the database."""

	def get(self, key):
		return frappe.cache.get_value(key)

	def set(self, key, value, ttl):
		frappe.cache.set_value(key, value, expires_in_sec=int(ttl))

	def delete(self, key):
		frappe.cache.delete_value(key)


def _host(url):
	from urllib.parse import urlparse

	return (urlparse(url or "").hostname or "").lower()


def resolve_rest_configuration_name(connection):
	name = connection.get("rest_configuration")
	if not name and connection.get("accredited_provider"):
		name = frappe.db.get_value("UAE Accredited Service Provider", connection.accredited_provider, "rest_configuration")
	return name


def rest_configuration(name, connection=None):
	"""Plain dict consumed by ``ASPRestEngine``; secrets are decrypted here and nowhere else."""
	doc = frappe.get_doc("ASP REST API Configuration", name)
	if not doc.enabled:
		frappe.throw(frappe._("ASP REST API Configuration {0} is disabled").format(name))
	if connection is not None and doc.tenant and doc.tenant != connection.tenant:
		frappe.throw(frappe._("ASP REST API Configuration {0} belongs to a different tenant").format(name))

	auth = {"type": doc.authentication_type or "None", "scope": doc.oauth_scope, "plugin": doc.auth_plugin,
		"token_content_type": doc.token_request_content_type,
		"custom_headers": loads(doc.custom_authentication_headers, {}) or {},
		"jwt_claims": loads(doc.jwt_claims, {}) or {}}
	for field in REST_AUTH_FIELDS:
		auth[field] = doc.get(field)
	for field in REST_AUTH_SECRETS:
		auth[field] = doc.get_password(field, raise_exception=False) if doc.get(field) else None

	environment = doc.environment
	base_url = None
	participant = {}
	if connection is not None:
		environment = connection.get("environment") or environment
		base_url = connection.get("base_url")
		for conn_field, auth_field in CONNECTION_OVERRIDES.items():
			if not connection.get(conn_field):
				continue
			if conn_field in SECRET_FIELDS:
				auth[auth_field] = connection.get_password(conn_field, raise_exception=False)
			else:
				auth[auth_field] = connection.get(conn_field)
		participant = {"participant_id": connection.get("participant_id"), "tin": connection.get("participant_tin")}
	base_url = base_url or (doc.production_base_url if environment == "Production" else doc.sandbox_base_url)

	hosts = {_host(u) for u in (doc.sandbox_base_url, doc.production_base_url, base_url, auth.get("token_url"),
		auth.get("refresh_token_url"))}
	hosts.update(h.strip().lower() for h in (doc.approved_hosts or "").splitlines())
	hosts.discard("")

	endpoints = {}
	for row in doc.endpoints:
		key = row.endpoint_name if (row.operation == "Custom Operation" and row.endpoint_name) else row.operation
		endpoints[key] = {"method": row.http_method, "url": row.relative_url, "enabled": row.enabled,
			"request_content_type": row.request_content_type, "response_content_type": row.response_content_type,
			"auth_required": row.authentication_required, "timeout": row.timeout, "retry": row.retry_enabled,
			"max_retries": row.maximum_retries, "idempotency": row.idempotency_enabled,
			"idempotency_header": row.idempotency_header}
	webhook = {}
	for row in doc.webhooks:
		if not row.webhook_enabled:
			continue
		from frappe.utils.password import get_decrypted_password

		secret = get_decrypted_password(row.doctype, row.name, "signing_secret", raise_exception=False) \
			if row.signing_secret else None
		webhook = {"enabled": 1, "auth_type": row.authentication_type, "secret": secret, "header": row.signature_header,
			"event_id_path": row.event_identifier_path, "event_type_path": row.event_type_path,
			"document_id_path": row.document_identifier_path, "status_path": row.status_path,
			"payload_mapping": row.payload_mapping, "document_events": row.document_events,
			"document_path": row.document_path, "document_base64": row.document_base64}
		break

	settings = frappe.get_cached_doc("E-Invoice Hub Settings")
	return {
		"name": doc.asp_name, "code": doc.asp_code, "environment": environment, "base_url": base_url,
		"allowed_hosts": sorted(hosts), "verify_ssl": bool(doc.verify_ssl),
		"max_response_bytes": max(int(doc.max_response_mb or 10), 1) * 1024 * 1024,
		"allow_insecure": bool(settings.get("allow_insecure_http")),
		"allow_private_hosts": bool(settings.get("allow_private_hosts")),
		"auth": auth, "endpoints": endpoints, "participant": participant,
		"headers": [{"name": r.header_name, "value": r.header_value, "value_type": r.value_type,
			"dynamic_value": r.dynamic_value, "enabled": r.enabled} for r in doc.headers],
		"request_mappings": [{"operation": r.operation, "source": r.source_field, "target": r.target_json_path,
			"data_type": r.data_type, "transformation": r.transformation, "condition": r.condition,
			"required": r.required, "default": r.default_value, "enabled": r.enabled} for r in doc.request_mappings],
		"response_mappings": [{"path": r.response_json_path, "target": r.target_platform_field,
			"operation": r.operation, "transformation": r.transformation, "default": r.default_value,
			"required": r.required, "enabled": r.enabled} for r in doc.response_mappings],
		"webhook": webhook, "incoming_list_path": doc.incoming_list_path,
	}


def asp_runtime(cfg, doc):
	"""Attach the REST configuration, token store and integration logger to an ASP connection config."""
	from thinknxg_einvoice_hub.core import integration_log

	name = resolve_rest_configuration_name(doc)
	cfg["rest"] = rest_configuration(name, doc) if name else {}
	cfg["token_store"] = CacheTokenStore()
	cfg["logger"] = lambda entry: integration_log.write(entry, tenant=doc.tenant, asp_connection=doc.name)
	return cfg
