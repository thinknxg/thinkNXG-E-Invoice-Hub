"""Transaction state machine.

    Received -> Normalized -> Validated -> Submitted -> Delivered
                     |             |            |
                     v             v            v
             Validation Failed   Retrying    Rejected
                                   |
                                   v
                                 Failed

Delivered, Rejected, Duplicate and Cancelled are terminal.
"""

from frappe.utils import now_datetime

from thinknxg_einvoice_hub.core.document_manager import audit
from thinknxg_einvoice_hub.exceptions import PermanentError

TERMINAL = ("Delivered", "Reported", "Rejected", "Duplicate", "Cancelled")
#: states from which a manual reprocess is allowed
REPROCESSABLE = ("Received", "Normalized", "Validated", "Validation Failed", "Retrying", "Failed")
#: a later document with the same number supersedes transactions in these states
SUPERSEDABLE = ("Validation Failed", "Rejected", "Failed", "Cancelled", "Duplicate")


def set_status(txn, status, message=None, level="Info", **fields):
	"""Move a transaction to a new status, save it and write the audit entry."""
	if txn.status in TERMINAL and status != txn.status:
		raise PermanentError(f"Transaction {txn.name} is {txn.status} and cannot move to {status}")
	previous = txn.status
	txn.status = status
	txn.update(fields)
	if status in ("Submitted", "Delivered", "Rejected") and txn.direction == "Outbound" and not txn.submitted_at:
		txn.submitted_at = now_datetime()
	if status == "Delivered" and not txn.delivered_at:
		txn.delivered_at = now_datetime()
	if status not in ("Retrying", "Failed") and "last_error" not in fields:
		txn.last_error = None
		txn.next_retry_at = None
	txn.save(ignore_permissions=True)
	if previous != status or message:
		audit(txn, f"status.{status.lower().replace(' ', '_')}", message or f"{previous} -> {status}", level)
	return txn
