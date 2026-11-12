import frappe
from frappe import _
from frappe.model.document import Document

from thinknxg_einvoice_hub.utils import sha256


class InvoicePayload(Document):
	"""Append-only record of every form an invoice took on its way through the hub."""

	def validate(self):
		if not self.is_new():
			frappe.throw(_("Invoice payloads are immutable"))
		self.sha256 = sha256(self.content or "")
