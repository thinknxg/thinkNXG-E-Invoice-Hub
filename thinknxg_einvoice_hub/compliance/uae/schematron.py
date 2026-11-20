"""Optional validation with the official PINT AE Schematron.

The official validation artefacts are published by OpenPeppol for the UAE Peppol
Authority (``resources.zip`` on https://docs.peppol.eu/poac/ae/pint-ae/, one for
Billing and one for Self-Billing). They are not bundled with this app: an operator
downloads them, unzips them on the server and sets, in the UAE Compliance Profile's
engine settings::

    {"schematron_dir": "/path/to/pint-ae-1.0.5/billing",
     "selfbilling_schematron_dir": "/path/to/pint-ae-1.0.5/sb",
     "official_validation": "if_configured"}

``official_validation`` is ``off``, ``if_configured`` (default) or ``required``.
With ``required`` a missing or unusable rule set blocks submission instead of
producing a warning.

When the resources or Saxon are missing, :func:`validate` returns a single
Warning (rule ``EIH-AE-090``) saying the official check did not run; it never
pretends to pass.
"""

from thinknxg_einvoice_hub.compliance.shared.schematron import _saxon, ruleset_version, run, stylesheets  # noqa: F401
from thinknxg_einvoice_hub.utils import issue

__all__ = ["NOT_RUN", "describe", "ruleset_version", "run", "stylesheets", "validate"]

NOT_RUN = "EIH-AE-090"


def describe(root_dir):
	"""What the country profile reports about the configured rules. The official PINT AE rule files
	do not state their version, so the operator's folder name is the only record of it."""
	if not root_dir:
		return None
	if not stylesheets(root_dir, False):
		return f"not found under {root_dir}"
	return ruleset_version(root_dir) or f"configured at {root_dir} (the rule files do not state a version)"


def validate(xml, profile, credit=False, selfbilling=False):
	"""Issues from the official Schematron, in the hub's issue format (severity, rule_id, field_path, message)."""
	key = "selfbilling_schematron_dir" if selfbilling else "schematron_dir"
	root_dir = (profile or {}).get(key)
	if not root_dir:
		return [issue("Warning", NOT_RUN, "document",
			f"Official PINT AE Schematron is not configured ({key} in engine settings); only hub checks ran")]
	if _saxon() is None:
		return [issue("Warning", NOT_RUN, "document",
			"Official PINT AE Schematron is configured but Saxon is not installed (pip install saxonche)")]
	if not stylesheets(root_dir, credit):
		return [issue("Warning", NOT_RUN, "document",
			f"No official Schematron stylesheets found under {root_dir}; check the folder layout")]
	out = []
	for flag, rule_id, text, location in run(xml, root_dir, credit):
		severity = "Error" if flag == "fatal" else "Warning"
		out.append(issue(severity, rule_id or "PINT-AE", location[:255], text[:1000]))
	return out
