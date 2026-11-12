"""Webhook manager: verify, record and process ERP and ASP events."""

import frappe

from thinknxg_einvoice_hub.asp_connectors.adapter_registry import get_adapter
from thinknxg_einvoice_hub.core import document_manager as dm
from thinknxg_einvoice_hub.erp_connectors import base_connector as erp
from thinknxg_einvoice_hub.erp_connectors.connector_registry import get_connector
from thinknxg_einvoice_hub.exceptions import HubError, PermanentError
from thinknxg_einvoice_hub.utils import loads, sha256

from thinknxg_einvoice_hub.webhook_security import verify_signature  # noqa: F401  (re-exported)


def find_duplicate(source_type, connection_name, event_id):
	"""An earlier delivery of the same event for the same connection, if any."""
	field = "erp_connection" if source_type == "ERP" else "asp_connection"
	return frappe.db.get_value("Webhook Event",
		{field: connection_name, "event_id": event_id, "signature_valid": 1, "status": ["in", ["Received", "Processed"]]},
		"name")


def record_event(source_type, connection, body, headers, signature_valid):
	text = body.decode("utf-8", errors="replace")
	payload = loads(text) if signature_valid else None
	event = frappe.get_doc({
		"doctype": "Webhook Event",
		"tenant": connection.tenant,
		"source_type": source_type,
		"erp_connection": connection.name if source_type == "ERP" else None,
		"asp_connection": connection.name if source_type == "ASP" else None,
		"event_type": (payload.get("event") if isinstance(payload, dict) else None) or "unknown",
		# until the provider's own event ID is known, the body hash identifies a redelivery
		"event_id": sha256(body) if signature_valid else None,
		"signature_valid": 1 if signature_valid else 0,
		"status": "Received" if signature_valid else "Ignored",
		"headers": frappe.as_json({k: v for k, v in headers.items()
			if k.lower() in ("content-type", "user-agent", "x-request-id", "x-frappe-event-type")}),
		# unauthenticated bodies are not stored, so the endpoint cannot be used to fill the database
		"payload": text[:1000000] if signature_valid else None,
		"error": None if signature_valid else "Signature verification failed",
		"received_at": frappe.utils.now_datetime(),
	})
	event.insert(ignore_permissions=True)
	return event


def process_event(webhook_event):
	"""Background job: act on a verified webhook event.

	The argument is not called ``event`` because that name is reserved by the job queue.
	"""
	event = webhook_event
	doc = frappe.get_doc("Webhook Event", event)
	if doc.status != "Received" or not doc.signature_valid:
		return
	payload = loads(doc.payload)
	if payload is None:
		payload = doc.payload
	try:
		transaction = _process_erp(doc, payload) if doc.source_type == "ERP" else _process_asp(doc, payload)
		doc.db_set({"status": "Processed" if transaction else "Ignored", "transaction": transaction})
	except HubError as e:
		doc.db_set({"status": "Failed", "error": str(e)[:1000]})
	except Exception as e:
		frappe.log_error(title=f"E-Invoice Hub webhook: {event}", message=frappe.get_traceback())
		doc.db_set({"status": "Failed", "error": str(e)[:1000]})
	frappe.db.commit()


def _process_erp(doc, payload):
	from thinknxg_einvoice_hub.services.invoice_service import ingest_outbound

	conn = frappe.get_doc("ERP Connection", doc.erp_connection)
	connector = get_connector(conn)
	parsed = connector.parse_webhook(payload)
	document_id, invoice = parsed.get("document_id"), parsed.get("invoice")
	if parsed.get("event") == "ignored" or not (document_id or invoice):
		return None
	if invoice is None:
		connector.require(erp.CAP_FETCH_INVOICE)
		invoice = connector.fetch_invoice(document_id)

	profiles = frappe.get_all(
		"Company Integration Profile",
		filters={"tenant": conn.tenant, "erp_connection": conn.name, "enabled": 1},
		fields=["name", "tax_id"],
	)
	if not profiles:
		raise PermanentError(f"No company profile uses ERP connection {conn.name}")
	profile = profiles[0]["name"]
	if len(profiles) > 1:
		supplier_tax_id = (connector.normalize_invoice(invoice).get("supplier") or {}).get("tax_id")
		match = [p["name"] for p in profiles if p["tax_id"] and p["tax_id"] == supplier_tax_id]
		if not match:
			raise PermanentError("Several company profiles use this ERP connection and none matches the supplier tax ID")
		profile = match[0]
	return ingest_outbound(conn.tenant, profile, invoice, erp_connection=conn.name, erp_document_id=document_id)


def _process_asp(doc, payload):
	from thinknxg_einvoice_hub.services.invoice_service import apply_asp_result, ingest_inbound

	conn = frappe.get_doc("ASP Connection", doc.asp_connection)
	parsed = get_adapter(conn).process_webhook(payload, loads(doc.headers, {}) or {})
	provider_event = parsed.get("event_id")
	if provider_event:
		# providers redeliver events; the same provider event ID is processed once only
		if frappe.db.exists("Webhook Event", {"asp_connection": conn.name, "event_id": str(provider_event),
				"name": ["!=", doc.name]}):
			doc.db_set({"duplicate": 1, "event_id": str(provider_event)[:255]})
			return None
		doc.db_set("event_id", str(provider_event)[:255])
	if parsed.get("event_type"):
		doc.db_set("event_type", str(parsed["event_type"])[:140])
	if parsed.get("kind") == "document":
		return ingest_inbound(conn.tenant, conn.name, parsed.get("payload"), asp_reference=parsed.get("reference"))

	reference = parsed.get("reference")
	if not reference:
		return None
	name = frappe.db.get_value(
		"Invoice Transaction",
		{"tenant": conn.tenant, "asp_connection": conn.name, "asp_reference": reference, "direction": "Outbound"},
		"name",
	)
	if not name:
		return None
	txn = frappe.get_doc("Invoice Transaction", name)
	dm.store_payload(txn, "ASP Response", parsed.get("raw") or payload)
	# statuses only move forward, so events arriving out of order cannot regress a document
	apply_asp_result(txn, parsed)
	return name
