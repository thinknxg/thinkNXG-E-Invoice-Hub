"""Retry engine: exponential backoff for temporary transmission failures."""

import frappe
from frappe.utils import add_to_date, cint, now_datetime

from thinknxg_einvoice_hub.core.transaction_manager import TERMINAL, set_status


def _settings():
	settings = frappe.get_cached_doc("E-Invoice Hub Settings")
	return max(cint(settings.max_retries), 0) or 6, max(cint(settings.retry_base_minutes), 1)


def schedule_retry(txn, error):
	"""Queue another attempt, or mark the transaction Failed once retries are exhausted."""
	if txn.status in TERMINAL:
		return
	max_retries, base_minutes = _settings()
	attempt = cint(txn.retry_count) + 1
	if attempt > max_retries:
		set_status(txn, "Failed", f"Gave up after {max_retries} retries: {error}", level="Error",
			last_error=error[:1000], next_retry_at=None)
		from thinknxg_einvoice_hub.services.invoice_service import sync_erp_status

		sync_erp_status(txn)
		return
	delay = min(base_minutes * (2 ** (attempt - 1)), 24 * 60)
	set_status(txn, "Retrying", f"Attempt {attempt} of {max_retries} in {delay} min: {error}", level="Warning",
		retry_count=attempt, next_retry_at=add_to_date(now_datetime(), minutes=delay), last_error=error[:1000])


def run_due_retries():
	"""Scheduler: re-queue transactions whose retry time has arrived."""
	from thinknxg_einvoice_hub.services.invoice_service import enqueue_processing

	due = frappe.get_all(
		"Invoice Transaction",
		filters={"status": "Retrying", "next_retry_at": ["<=", now_datetime()]},
		pluck="name",
		order_by="next_retry_at asc",
		limit=200,
	)
	for name in due:
		# push the retry time forward so the next scheduler tick does not queue the same job twice
		frappe.db.set_value("Invoice Transaction", name, "next_retry_at", add_to_date(now_datetime(), minutes=30),
			update_modified=False)
		enqueue_processing(name)
	return len(due)
