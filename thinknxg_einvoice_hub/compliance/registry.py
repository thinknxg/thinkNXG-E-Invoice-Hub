"""Compliance engine registry.

Other apps add country engines through the ``einvoice_hub_compliance_engines``
hook in their hooks.py: ``{"sa_zatca": "my_app.engines.ZatcaEngine"}``.
"""

from thinknxg_einvoice_hub.exceptions import PermanentError
from thinknxg_einvoice_hub.utils import hook_map, load_class

BUILTIN_ENGINES = {
	"uae_pint_ae": "thinknxg_einvoice_hub.compliance.uae.pint_ae.PintAEEngine",
}


def engine_paths():
	paths = dict(BUILTIN_ENGINES)
	paths.update(hook_map("einvoice_hub_compliance_engines"))
	return paths


def get_engine_class(code):
	path = engine_paths().get(code)
	if not path:
		raise PermanentError(f"No compliance engine registered for '{code}'")
	return load_class(path)


def get_engine(code, profile=None):
	return get_engine_class(code)(profile)
