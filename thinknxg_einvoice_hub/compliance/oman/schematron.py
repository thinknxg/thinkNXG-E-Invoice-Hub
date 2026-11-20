"""Optional validation with the official PINT OM Schematron.

The official validation artefacts are published by OpenPeppol for the Oman Tax
Authority (``resources.zip`` on https://docs.peppol.eu/poac/om/pint-om/, one for
Billing and one for Self-Billing). They are not bundled with this app: an operator
downloads them, unzips them on the server and sets, in the Oman Compliance
Profile's engine settings::

    {"schematron_dir": "/path/to/pint-om-resources-1.0.1",
     "selfbilling_schematron_dir": "/path/to/pint-om-sb-resources-1.0.1"}

Each directory must contain ``trn-invoice/schematron/*.xslt`` and
``trn-creditnote/schematron/*.xslt`` (the layout of the official zip). The compiled
XSLT 2.0 stylesheets are run with Saxon (``pip install saxonche``).

When the resources or Saxon are missing, :func:`validate` returns a single
Warning saying the official check did not run; it never pretends to pass.
"""

import os
import re
import threading
import xml.etree.ElementTree as ET

from thinknxg_einvoice_hub.utils import issue

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
	"""Version announced by the official rules (BTOM-META-001), e.g. ``1.0.1``."""
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


def validate(xml, profile, credit=False, selfbilling=False):
	"""Issues from the official Schematron, in the hub's issue format (severity, rule_id, field_path, message)."""
	key = "selfbilling_schematron_dir" if selfbilling else "schematron_dir"
	root_dir = (profile or {}).get(key)
	if not root_dir:
		return [issue("Warning", "EIH-OM-090", "document",
			f"Official PINT OM Schematron is not configured ({key} in engine settings); only hub checks ran")]
	if _saxon() is None:
		return [issue("Warning", "EIH-OM-090", "document",
			"Official PINT OM Schematron is configured but Saxon is not installed (pip install saxonche)")]
	if not stylesheets(root_dir, credit):
		return [issue("Warning", "EIH-OM-090", "document",
			f"No official Schematron stylesheets found under {root_dir}; check the folder layout")]
	out = []
	for flag, rule_id, text, location in run(xml, root_dir, credit):
		severity = "Error" if flag == "fatal" else "Warning"
		out.append(issue(severity, rule_id or "PINT-OM", location[:255], text[:1000]))
	return out
