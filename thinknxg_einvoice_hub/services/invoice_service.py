"""Universal transaction processing.

Outbound:  ERP payload -> canonical -> compliance validation -> compliance document
           -> designated ASP -> status -> back to the ERP
Inbound:   ASP document -> canonical -> validation / duplicate check -> destination
           company -> draft purchase invoice in the ERP

Processing always runs in a background job and is resumable: each stage stores
its output as an Invoice Payload, so a retry continues from what already exists.
"""

import frappe
from frappe import _

from thinknxg_einvoice_hub.asp_connectors import base_adapter as asp
from thinknxg_einvoice_hub.asp_connectors.adapter_registry import get_adapter
from thinknxg_einvoice_hub.canonical.invoice_schema import is_canonical, validate_structure
from thinknxg_einvoice_hub.canonical.normalizer import normalize
from thinknxg_einvoice_hub.core import document_manager as dm
from thinknxg_einvoice_hub.core import routing_engine
from thinknxg_einvoice_hub.core.company_manager import fill_party_from_profile, get_profile
from thinknxg_einvoice_hub.core.transaction_manager import REPROCESSABLE, SUPERSEDABLE, TERMINAL, set_status
from thinknxg_einvoice_hub.erp_connectors import base_connector as erp
from thinknxg_einvoice_hub.erp_connectors.connector_registry import get_connector
from thinknxg_einvoice_hub.exceptions import HubError, NotSupportedError, PermanentError, TransientError
from thinknxg_einvoice_hub.utils import dumps, has_errors, issue, loads

ASP_STATUS_MAP = {
	asp.ST_SUBMITTED: "Submitted",
	asp.ST_PENDING: "Submitted",
	asp.ST_DELIVERED: "Delivered",
	asp.ST_REJECTED: "Rejected",
}


LOCK_SECONDS = 900  # matches the job timeout; a crashed worker cannot block a document for longer


# ------------------------------------------------------------------ intake
def enqueue_processing(transaction, renormalize=False):
	frappe.enqueue(
		"thinknxg_einvoice_hub.services.invoice_service.process_transaction",
		queue="default",
		timeout=900,
		enqueue_after_commit=True,
		transaction=transaction,
		renormalize=renormalize,
	)


def ingest_outbound(tenant, company_profile, payload, erp_connection=None, erp_document_id=None):
	"""Register an outbound invoice coming from an ERP and queue it. Returns the transaction name."""
	profile = get_profile(company_profile, tenant)
	erp_connection = erp_connection or profile.erp_connection
	if erp_connection and frappe.db.get_value("ERP Connection", erp_connection, "tenant") != tenant:
		frappe.throw(_("ERP connection does not belong to this tenant"), frappe.PermissionError)

	if erp_connection and erp_document_id:
		existing = frappe.get_all(
			"Invoice Transaction",
			filters={
				"tenant": tenant,
				"direction": "Outbound",
				"erp_connection": erp_connection,
				"erp_document_id": str(erp_document_id),
				"status": ["not in", list(SUPERSEDABLE)],
			},
			pluck="name",
			limit=1,
		)
		if existing:
			return existing[0]

	txn = dm.create_transaction(
		tenant=tenant,
		company_profile=profile.name,
		direction="Outbound",
		erp_connection=erp_connection,
		erp_document_id=str(erp_document_id) if erp_document_id else None,
		asp_connection=profile.asp_connection,
		compliance_profile=profile.compliance_profile,
		erp_sync_status="Pending" if (erp_connection and profile.sync_status_to_erp) else "Not Applicable",
		source_erp=frappe.db.get_value("ERP Connection", erp_connection, "erp_connector") if erp_connection else None,
		accredited_provider=frappe.db.get_value("ASP Connection", profile.asp_connection, "accredited_provider")
		if profile.asp_connection else None,
	)
	dm.store_payload(txn, "Source ERP", payload)
	enqueue_processing(txn.name)
	return txn.name


def ingest_inbound(tenant, asp_connection, payload, asp_reference=None):
	"""Register a document received from an ASP and queue it. Returns the transaction name."""
	if frappe.db.get_value("ASP Connection", asp_connection, "tenant") != tenant:
		frappe.throw(_("ASP connection does not belong to this tenant"), frappe.PermissionError)
	if asp_reference:
		existing = frappe.get_all(
			"Invoice Transaction",
			filters={"tenant": tenant, "direction": "Inbound", "asp_connection": asp_connection,
				"asp_reference": asp_reference},
			pluck="name",
			limit=1,
		)
		if existing:
			return existing[0]
	txn = dm.create_transaction(
		tenant=tenant, direction="Inbound", asp_connection=asp_connection, asp_reference=asp_reference
	)
	dm.store_payload(txn, "ASP Inbound", payload)
	enqueue_processing(txn.name)
	return txn.name


# ------------------------------------------------------------------ pipeline
def process_transaction(transaction, renormalize=False):
	"""Background job entry point. Only one worker processes a given transaction at a time."""
	lock = frappe.cache.make_key(f"eih_processing:{transaction}")
	if not frappe.cache.set(lock, 1, nx=True, ex=LOCK_SECONDS):
		# another job (a repeated webhook, a scheduler tick, a manual reprocess) is already working on it
		return "busy"
	try:
		return _process_locked(transaction, renormalize)
	finally:
		frappe.cache.delete(lock)


def _process_locked(transaction, renormalize):
	txn = frappe.get_doc("Invoice Transaction", transaction)
	if txn.status in TERMINAL:
		return txn.status
	try:
		if txn.direction == "Outbound":
			_process_outbound(txn, renormalize)
		else:
			_process_inbound(txn, renormalize)
	except TransientError as e:
		from thinknxg_einvoice_hub.services.retry_service import schedule_retry

		frappe.db.rollback()
		schedule_retry(frappe.get_doc("Invoice Transaction", transaction), str(e))
	except HubError as e:
		frappe.db.rollback()
		_fail(transaction, str(e))
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error(title=f"E-Invoice Hub: {transaction}", message=frappe.get_traceback())
		_fail(transaction, f"Unexpected error: {e}")
	frappe.db.commit()
	return frappe.db.get_value("Invoice Transaction", transaction, "status")


def _fail(transaction, message):
	txn = frappe.get_doc("Invoice Transaction", transaction)
	if txn.status in TERMINAL:
		return
	set_status(txn, "Failed", message, level="Error", last_error=message[:1000], next_retry_at=None)
	sync_erp_status(txn)


def _dedupe_key(txn, inv):
	doc = inv.get("document") or {}
	owner = txn.company_profile if txn.direction == "Outbound" else (inv.get("supplier") or {}).get("tax_id")
	return "|".join(str(p or "") for p in (txn.tenant, txn.direction, owner, doc.get("document_type"),
		doc.get("invoice_number")))


def _find_duplicate(txn, key):
	rows = frappe.get_all(
		"Invoice Transaction",
		filters={"idempotency_key": key, "name": ["!=", txn.name], "status": ["not in", list(SUPERSEDABLE)]},
		pluck="name",
		order_by="creation asc",
		limit=1,
	)
	return rows[0] if rows else None


def _build_canonical(txn, raw, engine, company_profile=None):
	"""Normalise, enrich and structure-check. Returns ``(invoice, issues)``."""
	inv = normalize(raw)
	if company_profile and txn.direction == "Outbound":
		inv["supplier"] = fill_party_from_profile(inv.get("supplier") or {}, company_profile)
	inv = engine.enrich(inv)
	issues = validate_structure(inv)
	if company_profile and txn.direction == "Outbound":
		given = (inv.get("supplier") or {}).get("tax_id")
		if given and company_profile.tax_id and given != company_profile.tax_id:
			issues.append(issue("Error", "HUB-001", "supplier.tax_id",
				f"Supplier tax ID {given} does not match the company profile ({company_profile.tax_id})"))
	return inv, issues


def _finish_validation(txn, inv, issues, engine):
	"""Run compliance validation; returns True when the document may proceed."""
	if not has_errors(issues):
		issues = issues + engine.validate(inv)
	dm.set_validation_messages(txn, issues)
	if has_errors(issues):
		errors = sum(1 for i in issues if i["severity"] == "Error")
		set_status(txn, "Validation Failed", f"{errors} validation error(s)", level="Warning",
			validation_status="Failed")
		sync_erp_status(txn)
		return False
	set_status(txn, "Validated", validation_status="Passed")
	return True


def _process_outbound(txn, renormalize=False):
	if txn.status == "Submitted" or txn.asp_reference:
		# already with the ASP: never submit twice, just ask for the current status
		refresh_asp_status(txn.name)
		return
	profile = get_profile(txn.company_profile)
	engine = routing_engine.get_compliance_engine(txn.compliance_profile or profile.compliance_profile)

	# 1. ERP payload -> canonical
	inv = None if renormalize else dm.get_payload(txn.name, "Canonical")
	issues = []
	if inv is None:
		source = dm.get_payload(txn.name, "Source ERP")
		if source is None:
			raise PermanentError("Source ERP payload is missing")
		if is_canonical(source):
			raw = source
		elif txn.erp_connection:
			raw = get_connector(txn.erp_connection).normalize_invoice(source)
		else:
			raise PermanentError("Payload is not a canonical invoice and no ERP connection is set to map it")
		raw.setdefault("document", {})["direction"] = "OUTBOUND"
		inv, issues = _build_canonical(txn, raw, engine, profile)
		dm.store_payload(txn, "Canonical", inv)
		dm.apply_canonical_header(txn, inv)
		txn.idempotency_key = _dedupe_key(txn, inv)[:255]
		duplicate = _find_duplicate(txn, txn.idempotency_key)
		if duplicate:
			set_status(txn, "Duplicate", f"Same document already processed as {duplicate}", level="Warning",
				duplicate_of=duplicate, erp_sync_status="Not Applicable")
			return
		set_status(txn, "Normalized")
	frappe.db.commit()

	# 2. compliance validation
	if not _finish_validation(txn, inv, issues, engine):
		return
	frappe.db.commit()

	# 3. compliance document
	document = engine.generate_document(inv)
	dm.store_payload(txn, "Compliance Document", document["content"], document["format"])
	frappe.db.commit()

	# 4. routing + submission
	if not profile.auto_submit:
		dm.audit(txn, "submission.held", "Automatic submission is disabled for this company")
		return
	submit_to_asp(txn, profile, inv, document, engine)


def submit_to_asp(txn, profile, inv, document, engine):
	asp_doc = routing_engine.resolve_outbound_asp(txn, profile)
	adapter = get_adapter(asp_doc)
	adapter.require(asp.CAP_SUBMIT)
	if asp_doc.payload_format == "Canonical JSON":
		payload, fmt = dumps(inv), "JSON"
	else:
		payload, fmt = document["content"], document["format"]
	metadata = {
		"transaction": txn.name,
		# stable across retries, so a provider that honours idempotency keys never books a document twice
		"idempotency_key": txn.name,
		"invoice_number": txn.invoice_number,
		"document_type": txn.document_type,
		"format": fmt,
		"sender_id": engine.participant_id(inv.get("supplier")),
		"receiver_id": engine.participant_id(inv.get("customer")),
		"environment": asp_doc.environment,
		"_canonical": inv,
	}
	txn.asp_connection = asp_doc.name
	txn.accredited_provider = asp_doc.get("accredited_provider")
	txn.db_set({"asp_connection": asp_doc.name, "accredited_provider": asp_doc.get("accredited_provider"),
		"asp_submission_status": "Queued"})
	frappe.db.commit()
	if txn.document_type in ("SELF_BILLING_INVOICE", "SELF_BILLING_CREDIT_NOTE"):
		response = adapter.submit_self_billed_invoice(payload, metadata)
	elif txn.document_type == "CREDIT_NOTE":
		response = adapter.submit_credit_note(payload, metadata)
	else:
		response = adapter.submit_invoice(payload, metadata)
	dm.store_payload(txn, "ASP Response", response.get("raw") or {k: v for k, v in response.items() if k != "raw"})
	if response.get("reference"):
		# record the provider's document ID before anything else can fail: once it is stored, this
		# document is never submitted again (see the guard at the top of _process_outbound)
		txn.db_set("asp_reference", str(response["reference"])[:140])
	frappe.db.commit()
	apply_asp_result(txn, response)


# ASP acceptance, FTA reporting and Peppol delivery are three separate outcomes. Each only moves
# forward, so a late or repeated webhook can never roll a document back.
ASP_STATES = {asp.ST_SUBMITTED: "Submitted", asp.ST_PENDING: "Submitted", asp.ST_ACCEPTED: "Accepted",
	asp.ST_DELIVERED: "Accepted", asp.ST_REJECTED: "Rejected"}
FTA_STATES = {asp.FTA_PENDING: "Pending", asp.FTA_REPORTED: "Reported", asp.FTA_REJECTED: "Rejected"}
DELIVERY_STATES = {asp.DLV_PENDING: "Pending", asp.DLV_DELIVERED: "Delivered", asp.DLV_FAILED: "Failed"}
RANK = {"Not Submitted": 0, "Queued": 1, "Submitted": 2, "Accepted": 3, "Not Applicable": 0, "Pending": 1,
	"Reported": 2, "Delivered": 2, "Rejected": 3, "Failed": 2}


def apply_asp_result(txn, response):
	"""Apply a normalised ASP result (from submission, status sync or webhook)."""
	status = response.get("status")
	if status == asp.ST_FAILED:
		raise PermanentError(response.get("message") or "ASP reported a failure")
	if status and status not in ASP_STATES:
		raise PermanentError(f"ASP adapter returned an unknown status '{status}'")

	fields = {}

	def advance(fieldname, value):
		current = txn.get(fieldname)
		if value and value != current and RANK.get(value, 0) >= RANK.get(current or "", 0):
			fields[fieldname] = value
		return fields.get(fieldname) or current

	asp_state = advance("asp_submission_status", ASP_STATES.get(status))
	fta_state = advance("fta_status", FTA_STATES.get(response.get("fta_status")))
	delivery = DELIVERY_STATES.get(response.get("delivery_status"))
	if status == asp.ST_DELIVERED and not delivery:
		delivery = "Delivered"
	delivery_state = advance("delivery_status", delivery)

	if status and status != txn.asp_status:
		fields["asp_status"] = status
	if response.get("message") and str(response["message"])[:1000] != txn.asp_message:
		fields["asp_message"] = str(response["message"])[:1000]
	if response.get("error_code"):
		fields["asp_error_code"] = str(response["error_code"])[:140]
	for source, target in (("reference", "asp_reference"), ("submission_reference", "submission_reference"),
			("fta_reference", "fta_reference"), ("delivery_reference", "delivery_reference"),
			("fta_message", "fta_message"), ("delivery_message", "delivery_message")):
		if response.get(source) and not txn.get(target):
			fields[target] = str(response[source])[:1000 if target.endswith("message") else 140]
	if fields.get("fta_status") == "Reported":
		fields["fta_reported_at"] = frappe.utils.now_datetime()

	if "Rejected" in (asp_state, fta_state):
		overall, level = "Rejected", "Warning"
	elif delivery_state == "Delivered":
		overall, level = "Delivered", "Info"
	elif delivery_state == "Failed":
		overall, level = "Failed", "Error"
		fields["last_error"] = response.get("delivery_message") or response.get("message") or "Peppol delivery failed"
	elif asp_state in ("Submitted", "Accepted"):
		overall, level = "Submitted", "Info"
	else:
		overall, level = txn.status, "Info"

	if txn.status in TERMINAL:
		# the overall outcome is final; still record later reporting / delivery news
		if fields:
			txn.db_set(fields)
			dm.audit(txn, "status.update", ", ".join(f"{k}={v}" for k, v in fields.items() if k.endswith("status")) or
				"references updated", level="Warning" if fields.get("fta_status") == "Rejected" else "Info")
			if fields.get("fta_status") or fields.get("delivery_status"):
				sync_erp_status(txn)
		return
	changed = overall != txn.status or any(k in fields for k in ("fta_status", "delivery_status",
		"asp_submission_status"))
	if not fields and not changed:
		return
	set_status(txn, overall, response.get("message") if overall != txn.status else None, level=level, **fields)
	if changed:
		sync_erp_status(txn)


def _open(txn):
	"""True while any of the three outcomes can still change."""
	return bool(txn.asp_reference and txn.asp_connection) and (
		txn.status == "Submitted" or txn.fta_status == "Pending" or txn.delivery_status == "Pending"
	)


def refresh_asp_status(transaction):
	"""Ask the ASP for the current ASP, FTA reporting and delivery status of a submitted document."""
	txn = frappe.get_doc("Invoice Transaction", transaction)
	if not _open(txn):
		return txn.status
	adapter = get_adapter(txn.asp_connection)
	calls = []
	if adapter.supports(asp.CAP_STATUS):
		calls.append(adapter.get_document_status)
	if adapter.supports(asp.CAP_REPORTING_STATUS) and txn.fta_status not in ("Reported", "Rejected"):
		calls.append(adapter.get_reporting_status)
	if adapter.supports(asp.CAP_DELIVERY_STATUS) and txn.delivery_status not in ("Delivered", "Failed"):
		calls.append(adapter.get_delivery_status)
	for call in calls:
		try:
			apply_asp_result(txn, call(txn.asp_reference))
		except PermanentError as e:
			_fail(txn.name, str(e))
			break
		txn = frappe.get_doc("Invoice Transaction", transaction)
	return txn.status


def _process_inbound(txn, renormalize=False):
	asp_doc = frappe.get_doc("ASP Connection", txn.asp_connection)
	profile = get_profile(txn.company_profile) if txn.company_profile else None

	inv = None if renormalize else dm.get_payload(txn.name, "Canonical")
	issues = []
	engine = None
	if inv is None:
		raw_payload = dm.get_payload(txn.name, "ASP Inbound")
		if raw_payload is None:
			raise PermanentError("Inbound ASP payload is missing")
		received = get_adapter(asp_doc).receive_document(raw_payload)
		content = received["content"]
		if received["format"] == "JSON":
			content = loads(content)
		if is_canonical(content):
			raw = content
		else:
			# the buyer is unknown until the document is parsed, so pick the engine from the tenant's profiles
			engine = _inbound_engine(txn, profile)
			raw = engine.parse_document(content)
		raw.setdefault("document", {})["direction"] = "INBOUND"
		if not profile:
			profile = routing_engine.resolve_inbound_company(txn.tenant, normalize(raw))
			txn.company_profile = profile.name
			txn.compliance_profile = profile.compliance_profile
			txn.erp_connection = profile.erp_connection
		engine = routing_engine.get_compliance_engine(profile.compliance_profile)
		inv, issues = _build_canonical(txn, raw, engine)
		dm.store_payload(txn, "Canonical", inv)
		dm.apply_canonical_header(txn, inv)
		txn.idempotency_key = _dedupe_key(txn, inv)[:255]
		duplicate = _find_duplicate(txn, txn.idempotency_key)
		if duplicate:
			set_status(txn, "Duplicate", f"Same document already received as {duplicate}", level="Warning",
				duplicate_of=duplicate)
			return
		set_status(txn, "Normalized")
	frappe.db.commit()

	engine = engine or routing_engine.get_compliance_engine(txn.compliance_profile)
	if not _finish_validation(txn, inv, issues, engine):
		return
	frappe.db.commit()
	post_inbound_to_erp(txn, profile or get_profile(txn.company_profile), inv)


def _inbound_engine(txn, profile):
	if profile:
		return routing_engine.get_compliance_engine(profile.compliance_profile)
	names = frappe.get_all("Company Integration Profile", filters={"tenant": txn.tenant, "enabled": 1},
		pluck="compliance_profile")
	names = sorted({n for n in names if n})
	if not names:
		raise PermanentError("No enabled company profile exists for this tenant")
	return routing_engine.get_compliance_engine(names[0])


def post_inbound_to_erp(txn, profile, inv):
	"""Create the draft purchase invoice in the destination ERP."""
	if profile.inbound_action != "Create Draft Purchase Invoice" or not profile.erp_connection:
		txn.erp_sync_status = "Not Applicable"
		txn.save(ignore_permissions=True)
		dm.audit(txn, "inbound.held", "Inbound invoice held in the hub (no ERP posting configured)")
		return
	connector = get_connector(profile.erp_connection)
	connector.require(erp.CAP_PURCHASE_INVOICE)
	txn.erp_connection = profile.erp_connection
	document_id = connector.create_purchase_invoice(inv)
	dm.store_payload(txn, "ERP Response", {"purchase_invoice": document_id})
	set_status(txn, "Delivered", f"Draft purchase invoice {document_id} created in the ERP",
		erp_document_id=str(document_id), erp_sync_status="Synced", erp_sync_message=None)


# ------------------------------------------------------------------ ERP feedback
def sync_erp_status(txn):
	"""Send the current status of an outbound transaction back to the originating ERP."""
	if isinstance(txn, str):
		txn = frappe.get_doc("Invoice Transaction", txn)
	if txn.direction != "Outbound" or not txn.erp_connection or not txn.erp_document_id or not txn.company_profile:
		return
	if not frappe.db.get_value("Company Integration Profile", txn.company_profile, "sync_status_to_erp"):
		return
	try:
		connector = get_connector(txn.erp_connection)
		if not connector.supports(erp.CAP_STATUS_UPDATE):
			txn.db_set("erp_sync_status", "Not Applicable")
			return
		connector.update_invoice_status(txn.erp_document_id, txn.status, {
			"hub_transaction": txn.name,
			"invoice_number": txn.invoice_number,
			"asp_reference": txn.asp_reference,
			"asp_status": txn.asp_status,
			"asp_submission_status": txn.asp_submission_status,
			"fta_status": txn.fta_status,
			"delivery_status": txn.delivery_status,
			"message": txn.asp_message or txn.last_error,
			"messages": [
				{"severity": m.severity, "rule_id": m.rule_id, "field": m.field_path, "message": m.message}
				for m in txn.validation_messages
				if m.severity != "Info"
			],
		})
		txn.db_set({"erp_sync_status": "Synced", "erp_sync_message": f"Status '{txn.status}' sent"})
	except NotSupportedError as e:
		# e.g. a push-mode ERP without a status callback: nothing to send, not a failure
		txn.db_set({"erp_sync_status": "Not Applicable", "erp_sync_message": str(e)[:1000]})
	except Exception as e:
		# never let ERP feedback problems change the e-invoicing outcome; reconciliation retries this
		txn.db_set({"erp_sync_status": "Failed", "erp_sync_message": str(e)[:1000]})
		dm.audit(txn, "erp.sync_failed", str(e), level="Warning")


# ------------------------------------------------------------------ manual actions
def reprocess(transaction, renormalize=True):
	txn = frappe.get_doc("Invoice Transaction", transaction)
	if txn.status not in REPROCESSABLE:
		frappe.throw(_("A transaction in status {0} cannot be reprocessed").format(txn.status))
	txn.db_set({"retry_count": 0, "next_retry_at": None})
	dm.audit(txn, "transaction.reprocess", "Reprocess requested")
	enqueue_processing(txn.name, renormalize=renormalize)
	return txn.name
