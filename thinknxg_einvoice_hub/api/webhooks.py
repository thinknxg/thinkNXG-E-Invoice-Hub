"""Webhook endpoints for ERPs and ASPs.

    POST /api/method/thinknxg_einvoice_hub.api.webhooks.erp?connection=<ERP Connection>
    POST /api/method/thinknxg_einvoice_hub.api.webhooks.asp?connection=<ASP Connection>

These endpoints are public but every request must carry an HMAC-SHA256 signature
of the raw body, computed with the connection's webhook secret:

    X-EIH-Signature: <hex digest>            (also accepted: "sha256=<hex>")
    X-Frappe-Webhook-Signature: <base64>     (sent by ERPNext / thinkNXG ERP webhooks)

Requests are acknowledged immediately and processed in the background.
"""

import frappe
from frappe.rate_limiter import rate_limit

from thinknxg_einvoice_hub.services import webhook_service

MAX_BODY_BYTES = 10 * 1024 * 1024


def _handle(source_type, doctype, connection):
	# with a JSON body the framework does not merge query-string arguments, so read the URL directly
	connection = connection or frappe.request.args.get("connection")
	body = frappe.request.get_data() or b""
	if len(body) > MAX_BODY_BYTES:
		frappe.throw("Payload too large", frappe.ValidationError)
	if not connection or not frappe.db.exists(doctype, {"name": connection, "enabled": 1}):
		raise frappe.AuthenticationError("Unknown connection or invalid signature")
	conn = frappe.get_doc(doctype, connection)
	headers = frappe.request.headers
	if source_type == "ASP":
		# each provider authenticates webhooks its own way; the adapter decides
		try:
			from thinknxg_einvoice_hub.asp_connectors.adapter_registry import get_adapter

			valid = bool(get_adapter(conn).verify_webhook(body, headers))
		except Exception:
			valid = False
	else:
		secret = conn.get_password("webhook_secret", raise_exception=False) if conn.get("webhook_secret") else None
		valid = webhook_service.verify_signature(secret, body, headers)
	if valid:
		from thinknxg_einvoice_hub.utils import sha256

		duplicate = webhook_service.find_duplicate(source_type, conn.name, sha256(body))
		if duplicate:
			return {"received": True, "duplicate": True, "event": duplicate}
	event = webhook_service.record_event(source_type, conn, body, headers, valid)
	frappe.db.commit()
	if not valid:
		raise frappe.AuthenticationError("Unknown connection or invalid signature")
	frappe.enqueue(
		"thinknxg_einvoice_hub.services.webhook_service.process_event",
		queue="default",
		timeout=600,
		webhook_event=event.name,
	)
	return {"received": True, "event": event.name}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=600, seconds=60)
def erp(connection=None):
	return _handle("ERP", "ERP Connection", connection)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=600, seconds=60)
def asp(connection=None):
	return _handle("ASP", "ASP Connection", connection)
