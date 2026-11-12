"""Minimal deterministic XML writer and safe parser used by UBL-based engines."""

import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape, quoteattr

from thinknxg_einvoice_hub.exceptions import PermanentError

UBL_NS = {
	"cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
	"cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
}
INVOICE_NS = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
CREDIT_NOTE_NS = "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2"


class El:
	"""XML element; children that are ``None`` or empty are skipped on render."""

	def __init__(self, tag, text=None, attrs=None, children=None):
		self.tag = tag
		self.text = None if text in (None, "") else str(text)
		self.attrs = {k: v for k, v in (attrs or {}).items() if v not in (None, "")}
		self.children = [c for c in (children or []) if c is not None and not c.is_empty()]

	def is_empty(self):
		return self.text is None and not self.children

	def add(self, *children):
		self.children.extend(c for c in children if c is not None and not c.is_empty())
		return self

	def render(self, level=0):
		pad = "  " * level
		attrs = "".join(f" {k}={quoteattr(str(v))}" for k, v in self.attrs.items())
		if self.children:
			inner = "\n".join(c.render(level + 1) for c in self.children)
			return f"{pad}<{self.tag}{attrs}>\n{inner}\n{pad}</{self.tag}>"
		return f"{pad}<{self.tag}{attrs}>{escape(self.text or '')}</{self.tag}>"


def cbc(name, text, **attrs):
	return El(f"cbc:{name}", text, attrs)


def cac(name, *children):
	return El(f"cac:{name}", children=list(children))


def render_document(root_tag, root_ns, children):
	root = El(root_tag, attrs={"xmlns": root_ns, "xmlns:cac": UBL_NS["cac"], "xmlns:cbc": UBL_NS["cbc"]},
		children=children)
	return '<?xml version="1.0" encoding="UTF-8"?>\n' + root.render() + "\n"


def parse_xml(content):
	"""Parse untrusted XML. DTDs and entity declarations are refused outright."""
	if isinstance(content, bytes):
		content = content.decode("utf-8-sig")
	content = content.lstrip("﻿").strip()
	head = content[:4096].upper()
	if "<!DOCTYPE" in head or "<!ENTITY" in content.upper():
		raise PermanentError("XML documents with DTD or entity declarations are not accepted")
	try:
		return ET.fromstring(content)
	except ET.ParseError as e:
		raise PermanentError(f"Document is not well-formed XML: {e}") from e


def text_of(node, path, default=None):
	if node is None:
		return default
	found = node.find(path, UBL_NS)
	if found is None or found.text is None:
		return default
	return found.text.strip()


def attr_of(node, path, attr, default=None):
	if node is None:
		return default
	found = node.find(path, UBL_NS)
	return found.get(attr, default) if found is not None else default
