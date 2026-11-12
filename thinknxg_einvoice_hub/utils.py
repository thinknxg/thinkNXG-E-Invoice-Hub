"""Framework-independent helpers (no thinkNXG Framework imports here)."""

import hashlib
import importlib
import json
import re
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

TWO = Decimal("0.01")


def _split(path):
	return [p for p in re.sub(r"\[(\d+)\]", r".\1", path or "").split(".") if p != ""]


def get_path(data, path, default=None):
	"""Read ``a.b[0].c`` / ``a.b.0.c`` from nested dicts and lists."""
	cur = data
	for tok in _split(path):
		if isinstance(cur, dict):
			cur = cur.get(tok)
		elif isinstance(cur, list) and tok.isdigit() and int(tok) < len(cur):
			cur = cur[int(tok)]
		else:
			return default
		if cur is None:
			return default
	return cur


def set_path(data, path, value):
	"""Write a nested dict value, creating intermediate dicts."""
	toks = _split(path)
	cur = data
	for tok in toks[:-1]:
		nxt = cur.get(tok)
		if not isinstance(nxt, dict):
			nxt = {}
			cur[tok] = nxt
		cur = nxt
	cur[toks[-1]] = value


def deep_merge(base, extra):
	"""Merge ``extra`` into ``base`` without overwriting existing non-empty values."""
	for key, val in (extra or {}).items():
		if isinstance(val, dict) and isinstance(base.get(key), dict):
			deep_merge(base[key], val)
		elif base.get(key) in (None, "", [], {}):
			base[key] = val
	return base


def to_decimal(value, default=None):
	if value is None or value == "":
		return default
	if isinstance(value, Decimal):
		return value
	try:
		return Decimal(str(value).replace(",", "").strip())
	except (InvalidOperation, ValueError):
		return default


def money(value):
	"""Round half-up to 2 decimals; ``None`` stays ``None``."""
	d = to_decimal(value)
	return None if d is None else d.quantize(TWO, rounding=ROUND_HALF_UP)


def fnum(value, places=2):
	"""Decimal -> float rounded for JSON storage."""
	d = to_decimal(value)
	if d is None:
		return None
	q = Decimal(1).scaleb(-places)
	return float(d.quantize(q, rounding=ROUND_HALF_UP))


_DATE_FORMATS = ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%Y%m%d")


def to_iso_date(value, fmt=None):
	"""Return ``YYYY-MM-DD`` or ``None`` when the value cannot be parsed."""
	if value in (None, ""):
		return None
	if isinstance(value, datetime):
		return value.date().isoformat()
	if isinstance(value, date):
		return value.isoformat()
	text = str(value).strip()
	for f in ([fmt] if fmt else []) + list(_DATE_FORMATS):
		try:
			return datetime.strptime(text[:19] if "T" in f or " " in f else text[:10], f).date().isoformat()
		except ValueError:
			continue
	try:
		return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
	except ValueError:
		return None


def sha256(text):
	if isinstance(text, str):
		text = text.encode("utf-8")
	return hashlib.sha256(text).hexdigest()


def dumps(obj):
	return json.dumps(obj, indent=2, ensure_ascii=False, default=str)


def loads(text, default=None):
	if isinstance(text, (dict, list)):
		return text
	if not text:
		return default
	try:
		return json.loads(text)
	except (TypeError, ValueError):
		return default


def load_class(dotted_path):
	module, _, name = dotted_path.rpartition(".")
	return getattr(importlib.import_module(module), name)


def hook_map(hook_name):
	"""Read a dict-style hook (``{"code": "dotted.path"}``) contributed by any installed app."""
	try:
		import frappe

		raw = frappe.get_hooks(hook_name)
	except Exception:
		return {}
	out = {}
	if isinstance(raw, dict):
		for key, val in raw.items():
			out[key] = val[-1] if isinstance(val, (list, tuple)) else val
	return out


def issue(severity, rule_id, field_path, message):
	return {"severity": severity, "rule_id": rule_id, "field_path": field_path, "message": message}


def has_errors(issues):
	return any(i["severity"] == "Error" for i in issues)
