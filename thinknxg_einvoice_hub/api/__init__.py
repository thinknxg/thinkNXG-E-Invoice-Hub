"""Universal Integration API.

All endpoints live under ``/api/method/thinknxg_einvoice_hub.api.<module>.<function>``
and authenticate with an API key and secret (``Authorization: token <key>:<secret>``)
of a user listed on an Integration Tenant. Webhook endpoints authenticate with an
HMAC signature instead.
"""

import frappe
from frappe import _

from thinknxg_einvoice_hub.utils import loads


def json_arg(value, name):
	"""Accept a JSON object passed either as a nested JSON body value or as a JSON string."""
	if isinstance(value, (dict, list)):
		return value
	parsed = loads(value) if isinstance(value, str) else None
	if parsed is None:
		frappe.throw(_("'{0}' must be a JSON object").format(name))
	return parsed


def get_transaction(name, tenant):
	"""Load a transaction and confirm it belongs to the caller's tenant."""
	if not name or frappe.db.get_value("Invoice Transaction", name, "tenant") != tenant:
		frappe.throw(_("Transaction not found"), frappe.DoesNotExistError)
	return frappe.get_doc("Invoice Transaction", name)
