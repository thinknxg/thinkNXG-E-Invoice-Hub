"""Configurable ERP-field -> canonical-field mapping engine.

A mapping is a plain dict so it can be stored in a Mapping Configuration record,
shipped inside a connector, or written by hand::

    {
      "line_source_path": "items",
      "defaults": {"document": {"currency": "AED"}},
      "rules": [
        {"scope": "Header", "source_path": "DocNum", "canonical_path": "document.invoice_number", "required": 1},
        {"scope": "Header", "source_path": "DocDate", "canonical_path": "document.invoice_date",
         "transform": "Date", "transform_arg": "%d/%m/%Y"},
        {"scope": "Line", "source_path": "Quantity", "canonical_path": "quantity", "transform": "Number"},
        {"scope": "Line", "source_path": "VatGroup", "canonical_path": "tax_category",
         "transform": "Value Map", "transform_arg": "{\"S1\": \"STANDARD\", \"Z0\": \"ZERO_RATED\"}"}
      ]
    }

Header rules write absolute canonical paths; line rules read and write relative
to each element of ``line_source_path``.
"""

import copy
import json

from thinknxg_einvoice_hub.canonical.invoice_schema import empty_invoice
from thinknxg_einvoice_hub.exceptions import MappingError
from thinknxg_einvoice_hub.utils import get_path, set_path, to_decimal, to_iso_date


def _transform(value, kind, arg):
	kind = (kind or "None").strip()
	if kind == "Constant":
		return arg
	if value is None:
		return None
	if kind == "None":
		return value
	if kind == "Upper":
		return str(value).upper()
	if kind == "Lower":
		return str(value).lower()
	if kind == "Strip":
		return str(value).strip()
	if kind == "Date":
		return to_iso_date(value, (arg or "").strip() or None)
	if kind == "Number":
		num = to_decimal(value)
		return float(num) if num is not None else None
	if kind == "Boolean":
		return str(value).strip().lower() in ("1", "true", "yes", "y")
	if kind == "Value Map":
		try:
			table = json.loads(arg or "{}")
		except ValueError as e:
			raise MappingError(f"Value Map argument is not valid JSON: {e}") from e
		return table.get(str(value), table.get("*", value))
	raise MappingError(f"Unknown transform '{kind}'")


def _apply(rule, source, target, errors, context):
	value = get_path(source, rule.get("source_path")) if rule.get("source_path") else None
	value = _transform(value, rule.get("transform"), rule.get("transform_arg"))
	if value in (None, "") and rule.get("default_value") not in (None, ""):
		value = rule["default_value"]
	if value in (None, ""):
		if rule.get("required"):
			errors.append(f"{context}: required ERP field '{rule.get('source_path')}' is missing")
		return
	set_path(target, rule["canonical_path"], value)


def apply_mapping(source, mapping):
	"""Map an ERP payload to a canonical invoice. Raises ``MappingError`` on required-field gaps."""
	if not isinstance(source, dict):
		raise MappingError("ERP payload must be a JSON object to apply a mapping")
	inv = empty_invoice()
	for section, values in copy.deepcopy(mapping.get("defaults") or {}).items():
		if isinstance(values, dict) and isinstance(inv.get(section), dict):
			inv[section].update(values)
		else:
			inv[section] = values

	rules = mapping.get("rules") or []
	errors = []
	for rule in rules:
		if (rule.get("scope") or "Header") == "Header":
			_apply(rule, source, inv, errors, "header")

	line_rules = [r for r in rules if r.get("scope") == "Line"]
	if line_rules:
		src_lines = get_path(source, mapping.get("line_source_path") or "lines") or []
		if isinstance(src_lines, dict):
			src_lines = [src_lines]
		for i, src in enumerate(src_lines):
			line = {}
			for rule in line_rules:
				_apply(rule, src, line, errors, f"line {i + 1}")
			inv["lines"].append(line)

	if errors:
		raise MappingError("; ".join(errors))
	return inv
