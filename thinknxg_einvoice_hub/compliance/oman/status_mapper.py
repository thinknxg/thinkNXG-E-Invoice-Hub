"""Oman provider statuses -> the hub's three independent outcomes.

Under the Oman 5-corner model [OM-SRA 2.3] two Peppol Message Level Status (MLS)
messages come back to the seller's accredited provider (C2):

* MLS (invoice), C3 -> C2: did the buyer's provider accept and deliver the invoice?
  -> the hub's **Peppol delivery** status.
* MLS (TDD), C5 -> C2: did the Tax Authority's access point accept the Tax Data
  Document? -> the hub's **tax-authority reporting** status.

Both use response codes AP (delivered, confirmed), AB (delivered, not confirmed)
and RE (rejected / failed). A provider adapter passes them through as
``invoice_mls_code`` and ``tdd_mls_code`` in its normalised result; this module
turns them into ``delivery_status`` and ``fta_status``. Neither code is ever
inferred from a successful API submission alone.
"""

from thinknxg_einvoice_hub.asp_connectors import base_adapter as asp
from thinknxg_einvoice_hub.compliance.oman import constants as C

DELIVERY = {"AP": asp.DLV_DELIVERED, "AB": asp.DLV_DELIVERED, "RE": asp.DLV_FAILED}
REPORTING = {"AP": asp.FTA_REPORTED, "AB": asp.FTA_REPORTED, "RE": asp.FTA_REJECTED}


def apply(response):
	"""Return a copy of a normalised adapter result with Oman MLS codes translated."""
	out = dict(response or {})
	inv_code = (out.get("invoice_mls_code") or "").upper()
	tdd_code = (out.get("tdd_mls_code") or "").upper()
	if inv_code in DELIVERY and not out.get("delivery_status"):
		out["delivery_status"] = DELIVERY[inv_code]
		out.setdefault("delivery_message", f"MLS {inv_code}: {C.MLS_CODES[inv_code]}")
	if tdd_code in REPORTING and not out.get("fta_status"):
		out["fta_status"] = REPORTING[tdd_code]
		out.setdefault("fta_message", f"TDD MLS {tdd_code}: {C.MLS_CODES[tdd_code]}")
	return out


def map_status(raw):
	"""Single status word -> generic lifecycle value, or ``None``."""
	code = (raw or "").strip().upper()
	if code in ("AP", "AB"):
		return "DELIVERED"
	if code == "RE":
		return "REJECTED"
	return None
