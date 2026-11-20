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

from thinknxg_einvoice_hub.compliance.shared.schematron import (  # noqa: F401  (re-exported)
	_saxon,
	ruleset_version,
	run,
	stylesheets,
)
from thinknxg_einvoice_hub.utils import issue

__all__ = ["ruleset_version", "run", "stylesheets", "validate"]


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
