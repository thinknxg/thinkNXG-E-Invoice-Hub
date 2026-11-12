import frappe
from frappe import _
from frappe.model.document import Document

from thinknxg_einvoice_hub.core.tenant_manager import assert_same_tenant, validate_tenant_on_doc


class CompanyIntegrationProfile(Document):
	def validate(self):
		validate_tenant_on_doc(self)
		assert_same_tenant(self, "erp_connection", "ERP Connection")
		assert_same_tenant(self, "asp_connection", "ASP Connection")
		self.tax_id = (self.tax_id or "").replace(" ", "")
		self.country_code = (self.country_code or "").upper()
		self.set_participant_id()
		self.check_unique_tax_id()

	def set_participant_id(self):
		from thinknxg_einvoice_hub.core.routing_engine import get_compliance_engine

		engine = get_compliance_engine(self.compliance_profile)
		party = engine.enrich({"supplier": {"tax_id": self.tax_id, "tin": self.tin,
			"address": {"country": self.country_code}}})["supplier"]
		self.tin = party.get("tin")
		self.participant_id = engine.participant_id(party)

	def check_unique_tax_id(self):
		other = frappe.db.get_value("Company Integration Profile",
			{"tenant": self.tenant, "tax_id": self.tax_id, "name": ["!=", self.name]}, "name")
		if other:
			frappe.throw(_("Company profile {0} already uses tax ID {1} in this tenant").format(other, self.tax_id))
