import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from thinknxg_einvoice_hub.core.tenant_manager import assert_same_tenant, validate_tenant_on_doc

PROVIDER = "microvista"


class MicrovistaSettings(Document):
	"""Dedicated settings for Microvista: one record per tenant company.

	Credentials live on the linked ASP Connection (encrypted); the API contract lives on the linked
	ASP REST API Configuration. Nothing here contains a Microvista endpoint, because none has been verified.
	"""

	def validate(self):
		validate_tenant_on_doc(self)
		assert_same_tenant(self, "company_profile", "Company Integration Profile")
		assert_same_tenant(self, "asp_connection", "ASP Connection")
		assert_same_tenant(self, "rest_configuration", "ASP REST API Configuration", allow_shared=True)
		if self.asp_connection and frappe.db.get_value("ASP Connection", self.asp_connection, "asp_provider") != PROVIDER:
			frappe.throw(_("ASP Connection {0} is not a Microvista connection").format(self.asp_connection))

	def before_save(self):
		if not self.asp_connection:
			conn = frappe.get_doc({
				"doctype": "ASP Connection",
				"connection_name": f"Microvista - {self.settings_name}",
				"tenant": self.tenant,
				"asp_provider": PROVIDER,
				"accredited_provider": PROVIDER if frappe.db.exists("UAE Accredited Service Provider", PROVIDER) else None,
				"environment": self.environment,
				"auth_type": "None",
			}).insert()
			self.asp_connection = conn.name
		conn = frappe.get_doc("ASP Connection", self.asp_connection)
		conn.update({
			"environment": self.environment,
			"rest_configuration": self.rest_configuration,
			"participant_id": self.participant_id,
			"participant_tin": self.participant_tin,
		})
		conn.save()

	def _adapter(self):
		from thinknxg_einvoice_hub.asp_connectors.adapter_registry import get_adapter

		return get_adapter(frappe.get_doc("ASP Connection", self.asp_connection))

	@frappe.whitelist()
	def get_readiness(self):
		self.check_permission("read")
		return self._adapter().readiness()

	@frappe.whitelist()
	def verify_credentials(self):
		self.check_permission("write")
		try:
			status = f"Success: {self._adapter().verify_credentials()}"
		except Exception as e:
			status = f"Failed: {e}"
		self.db_set({"last_test_status": status[:1000], "last_tested_on": now_datetime()})
		return status
