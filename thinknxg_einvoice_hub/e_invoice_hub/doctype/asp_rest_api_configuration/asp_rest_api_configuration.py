from urllib.parse import urlparse

import frappe
from frappe import _
from frappe.model.document import Document

from thinknxg_einvoice_hub.core.tenant_manager import is_hub_admin, validate_tenant_on_doc
from thinknxg_einvoice_hub.utils import loads

URL_FIELDS = ("sandbox_base_url", "production_base_url", "token_url", "refresh_token_url")


class ASPRESTAPIConfiguration(Document):
	"""API contract of one provider: authentication, endpoints, headers, mappings and webhooks."""

	def validate(self):
		# a configuration without a tenant is a shared template and only hub administrators may manage it
		if self.tenant or not is_hub_admin():
			validate_tenant_on_doc(self)
		self.validate_urls()
		self.validate_json()
		self.validate_rows()
		self.active_base_url = self.production_base_url if self.environment == "Production" else self.sandbox_base_url

	def validate_urls(self):
		insecure = frappe.db.get_single_value("E-Invoice Hub Settings", "allow_insecure_http")
		for field in URL_FIELDS:
			value = (self.get(field) or "").strip()
			if not value or value.startswith("/"):
				continue  # token URLs may be relative to the base URL
			parsed = urlparse(value)
			if not parsed.hostname or parsed.scheme not in ("https", "http"):
				frappe.throw(_("{0} is not a valid URL").format(self.meta.get_label(field)))
			if parsed.scheme != "https" and not insecure:
				frappe.throw(_("{0} must use HTTPS").format(self.meta.get_label(field)))
			if parsed.username or parsed.password:
				frappe.throw(_("{0} must not contain credentials").format(self.meta.get_label(field)))

	def validate_json(self):
		for field in ("custom_authentication_headers", "jwt_claims"):
			if self.get(field) and not isinstance(loads(self.get(field)), dict):
				frappe.throw(_("{0} must be a JSON object").format(self.meta.get_label(field)))
		for row in self.webhooks:
			if row.payload_mapping and not isinstance(loads(row.payload_mapping), dict):
				frappe.throw(_("Webhook row {0}: Payload Mapping must be a JSON object").format(row.idx))
			if row.signature_header and row.signature_header.strip().lower() == "authorization":
				frappe.throw(_("Webhook row {0}: the Authorization header cannot carry a webhook signature").format(row.idx))

	def validate_rows(self):
		from thinknxg_einvoice_hub.exceptions import MappingError
		from thinknxg_einvoice_hub.services.asp_rest_engine import transform, transformations

		seen = set()
		for row in self.endpoints:
			key = row.endpoint_name if row.operation == "Custom Operation" else row.operation
			if row.enabled and key in seen:
				frappe.throw(_("Endpoint row {0}: operation {1} is configured twice").format(row.idx, key))
			seen.add(key)
			if urlparse(row.relative_url or "").scheme and urlparse(row.relative_url).scheme != "https" \
					and not frappe.db.get_single_value("E-Invoice Hub Settings", "allow_insecure_http"):
				frappe.throw(_("Endpoint row {0}: absolute URLs must use HTTPS").format(row.idx))
		table = transformations()
		for label, rows in (("Request mapping", self.request_mappings), ("Response mapping", self.response_mappings)):
			for row in rows:
				try:
					transform(None, row.transformation, table)  # checks every step is a registered transformation
				except MappingError as e:
					frappe.throw(_("{0} row {1}: {2}").format(label, row.idx, str(e)))

	@frappe.whitelist()
	def verify_credentials(self):
		"""Check the default credentials stored on this configuration against the provider."""
		self.check_permission("write")
		from thinknxg_einvoice_hub.asp_connectors.generic_rest.configured import ConfiguredRestAdapter
		from thinknxg_einvoice_hub.core.connections import CacheTokenStore, rest_configuration
		from thinknxg_einvoice_hub.core import integration_log

		try:
			adapter = ConfiguredRestAdapter({
				"name": self.name,
				"rest": rest_configuration(self.name),
				"token_store": CacheTokenStore(),
				"logger": lambda entry: integration_log.write(entry, tenant=self.tenant),
			})
			return f"Success: {adapter.verify_credentials()}"
		except Exception as e:
			return f"Failed: {e}"
