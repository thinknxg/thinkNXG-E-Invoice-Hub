import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from thinknxg_einvoice_hub.core.tenant_manager import assert_same_tenant, validate_tenant_on_doc
from thinknxg_einvoice_hub.utils import loads


class ERPConnection(Document):
	def validate(self):
		validate_tenant_on_doc(self)
		assert_same_tenant(self, "mapping_configuration", "Mapping Configuration", allow_shared=True)
		for field in ("extra_config", "polling_filters"):
			if self.get(field) and not isinstance(loads(self.get(field)), dict):
				frappe.throw(_("{0} must be a JSON object").format(self.meta.get_label(field)))

	@frappe.whitelist()
	def test_connection(self):
		self.check_permission("write")
		from thinknxg_einvoice_hub.erp_connectors.connector_registry import get_connector

		try:
			status = f"Success: {get_connector(self).test_connection()}"
		except Exception as e:
			status = f"Failed: {e}"
		self.db_set({"last_test_status": status[:140], "last_tested_on": now_datetime()})
		return status
