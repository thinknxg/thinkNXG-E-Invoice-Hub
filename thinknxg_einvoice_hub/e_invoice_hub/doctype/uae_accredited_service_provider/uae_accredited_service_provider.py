import frappe
from frappe import _
from frappe.model.document import Document


class UAEAccreditedServiceProvider(Document):
	"""Directory entry. Accreditation, integration progress and production readiness are separate facts."""

	def validate(self):
		if self.production_verified and not self.sandbox_tested:
			frappe.throw(_("A provider cannot be production verified before it is sandbox tested"))
		if self.production_verified and self.integration_status != "Production Verified":
			self.integration_status = "Production Verified"
		elif self.sandbox_tested and self.integration_status in ("Not Started", "Skeleton - Pending API Documentation",
				"In Development"):
			self.integration_status = "Sandbox Tested"
		if self.adapter:
			self.supported_capabilities = self.describe_capabilities()

	def describe_capabilities(self):
		from thinknxg_einvoice_hub.asp_connectors.adapter_registry import get_adapter_class

		try:
			cls = get_adapter_class(self.adapter)
		except Exception:
			return None
		if cls.capabilities:
			return ", ".join(sorted(cls.capabilities))
		return "Follows the operations configured in the ASP REST API Configuration"
