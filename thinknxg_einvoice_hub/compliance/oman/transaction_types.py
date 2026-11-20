"""BTOM-001 invoice transaction type: a 20-position bitmap (CL-03-OM).

The canonical invoice may carry it in three ways, in order of precedence:

1. ``document.transaction_type_flags`` as the 20-character string;
2. ``extensions.om.transaction_types`` as a list of names from ``constants.TRANSACTION_TYPES``;
3. nothing: the engine derives Full Tax Invoice (plus Self-billed for self-billing documents).
"""

import re

from thinknxg_einvoice_hub.compliance.oman import constants as C

FLAGS_RE = re.compile(r"^[01]{20}$")


def build(names):
	bits = ["0"] * C.FLAG_LENGTH
	for name in names:
		bits[C.TRANSACTION_TYPES.index(name)] = "1"
	return "".join(bits)


def names(flags):
	"""Names of the defined positions that are set."""
	if not flags or not FLAGS_RE.match(flags):
		return []
	return [n for i, n in enumerate(C.TRANSACTION_TYPES) if flags[i] == "1"]


def has(flags, name):
	return name in names(flags)


def requested(invoice):
	return ((invoice.get("extensions") or {}).get("om") or {}).get("transaction_types")


def derive(invoice):
	"""Return the 20-character flags for an invoice, deriving them when absent."""
	doc = invoice.get("document") or {}
	given = (doc.get("transaction_type_flags") or "").strip()
	if len(given) == C.FLAG_LENGTH:
		return given
	ext = requested(invoice)
	if ext:
		if all(n in C.TRANSACTION_TYPES for n in ext):
			return build(ext)
		return None  # the validator reports the unknown names
	selected = ["FULL_TAX_INVOICE"]
	if doc.get("document_type") in C.SELF_BILLING:
		selected.append("SELF_BILLED")
	return build(selected)


def conflicts(flags):
	"""Pairs of set positions that PINT OM forbids together."""
	active = set(names(flags))
	return [(a, b) for a, b in C.INCOMPATIBLE_TYPES if a in active and b in active]
