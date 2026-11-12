import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from thinknxg_einvoice_hub.core.tenant_manager import assert_same_tenant, validate_tenant_on_doc
from thinknxg_einvoice_hub.utils import loads


class ASPConnection(Document):
	def validate(self):
		validate_tenant_on_doc(self)
		self.apply_directory_entry()
		assert_same_tenant(self, "rest_configuration", "ASP REST API Configuration", allow_shared=True)
		if self.extra_config and not isinstance(loads(self.extra_config), dict):
			frappe.throw(_("Extra Configuration must be a JSON object"))
		if self.asp_provider == "sandbox" and self.environment == "Production":
			frappe.throw(_("The sandbox provider cannot be used with the Production environment"))

	def apply_directory_entry(self):
		"""Choosing a provider from the directory fills in its adapter and API configuration."""
		if not self.accredited_provider:
			return
		entry = frappe.db.get_value("UAE Accredited Service Provider", self.accredited_provider,
			["adapter", "rest_configuration", "enabled"], as_dict=True)
		if not entry or not entry.enabled:
			frappe.throw(_("Provider {0} is not enabled in the directory").format(self.accredited_provider))
		if entry.adapter and (not self.asp_provider or self.has_value_changed("accredited_provider")):
			self.asp_provider = entry.adapter
		if entry.rest_configuration and not self.rest_configuration:
			self.rest_configuration = entry.rest_configuration

	@frappe.whitelist()
	def test_connection(self):
		self.check_permission("write")
		from thinknxg_einvoice_hub.asp_connectors.adapter_registry import get_adapter

		try:
			status = f"Success: {get_adapter(self).test_connection()}"
		except Exception as e:
			status = f"Failed: {e}"
		self.db_set({"last_test_status": status[:140], "last_tested_on": now_datetime()})
		return status
