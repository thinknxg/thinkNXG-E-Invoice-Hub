import frappe
from frappe import _
from frappe.model.document import Document

from thinknxg_einvoice_hub.core.tenant_manager import is_hub_admin, validate_tenant_on_doc
from thinknxg_einvoice_hub.utils import loads


class MappingConfiguration(Document):
	def validate(self):
		if self.tenant or not is_hub_admin():
			validate_tenant_on_doc(self)
		if self.defaults and not isinstance(loads(self.defaults), dict):
			frappe.throw(_("Canonical Defaults must be a JSON object"))
		for row in self.rules:
			if row.transform == "Value Map" and not isinstance(loads(row.transform_arg), dict):
				frappe.throw(_("Row {0}: Value Map needs a JSON object as its argument").format(row.idx))
			if row.transform != "Constant" and not row.source_path and not row.default_value:
				frappe.throw(_("Row {0}: set an ERP field path, a default value or a Constant transform").format(row.idx))
