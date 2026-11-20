"""Run official Peppol PINT Schematron artefacts (compiled XSLT 2.0) with Saxon.

Shared by the country engines. The official artefacts are never bundled with the app:
an operator downloads them from the publishing authority and points the engine
settings at the unzipped folder. Each folder must contain
``trn-invoice/schematron/*.xslt`` and ``trn-creditnote/schematron/*.xslt``.
"""

import os
import re
import threading
import xml.etree.ElementTree as ET

SVRL = "{http://purl.oclc.org/dsdl/svrl}"
_lock = threading.Lock()
_compiled = {}


def _saxon():
	try:
		import saxonche  # noqa: F401
		return saxonche
	except ImportError:
		return None


def stylesheets(root_dir, credit):
	folder = os.path.join(root_dir, "trn-creditnote" if credit else "trn-invoice", "schematron")
	if not os.path.isdir(folder):
		return []
	return sorted(os.path.join(folder, n) for n in os.listdir(folder) if n.endswith(".xslt"))


def ruleset_version(root_dir):
	"""Version announced by the official rules (``Ruleset version x.y.z``), e.g. ``1.0.1``."""
	for path in stylesheets(root_dir, False) + stylesheets(root_dir, True):
		with open(path, encoding="utf-8") as f:
			m = re.search(r"Ruleset version ([0-9.]+)", f.read())
		if m:
			return m.group(1)
	return None


def _executables(paths):
	saxon = _saxon()
	key = tuple(paths)
	with _lock:
		if key not in _compiled:
			proc = saxon.PySaxonProcessor(license=False)
			xslt = proc.new_xslt30_processor()
			_compiled[key] = (proc, [(p, xslt.compile_stylesheet(stylesheet_file=p)) for p in paths])
		return _compiled[key]


def run(xml, root_dir, credit):
	"""Raw SVRL findings: list of ``(flag, rule_id, text, location)``."""
	proc, execs = _executables(stylesheets(root_dir, credit))
	findings = []
	with _lock:
		node = proc.parse_xml(xml_text=xml)
		for _path, ex in execs:
			svrl = ex.transform_to_string(xdm_node=node)
			for fa in ET.fromstring(svrl).iter(SVRL + "failed-assert"):
				text_el = fa.find(SVRL + "text")
				text = re.sub(r"\s+", " ", "".join(text_el.itertext())).strip() if text_el is not None else ""
				findings.append((fa.get("flag") or "fatal", fa.get("id") or "", text, fa.get("location") or ""))
	return findings
