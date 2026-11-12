"""ASP adapter registry.

Additional adapters register through the ``einvoice_hub_asp_adapters`` hook::

    einvoice_hub_asp_adapters = {"my_asp": "my_app.adapters.MyASPAdapter"}
"""

from thinknxg_einvoice_hub.exceptions import PermanentError
from thinknxg_einvoice_hub.utils import hook_map, load_class

_P = "thinknxg_einvoice_hub.asp_connectors"
BUILTIN_ADAPTERS = {
	"sandbox": f"{_P}.sandbox.adapter.SandboxAdapter",
	"generic_rest": f"{_P}.generic_rest.adapter.GenericRestAdapter",
	"rest_config": f"{_P}.generic_rest.configured.ConfiguredRestAdapter",
	"microvista": f"{_P}.uae.microvista.adapter.MicrovistaAdapter",
	"wafeq": f"{_P}.uae.wafeq.adapter.WafeqAdapter",
	"flick": f"{_P}.uae.flick.adapter.FlickAdapter",
	"marmin": f"{_P}.uae.marmin.adapter.MarminAdapter",
	"suntech": f"{_P}.uae.suntech.adapter.SuntechAdapter",
	"fynamics": f"{_P}.uae.fynamics.adapter.FynamicsAdapter",
	"comarch": f"{_P}.comarch.adapter.ComarchAdapter",
	"pagero": f"{_P}.pagero.adapter.PageroAdapter",
	"avalara": f"{_P}.avalara.adapter.AvalaraAdapter",
	"cleartax": f"{_P}.cleartax.adapter.ClearTaxAdapter",
	"cygnet": f"{_P}.cygnet.adapter.CygnetAdapter",
	"edicom": f"{_P}.edicom.adapter.EdicomAdapter",
}


def adapter_paths():
	paths = dict(BUILTIN_ADAPTERS)
	paths.update(hook_map("einvoice_hub_asp_adapters"))
	return paths


def get_adapter_class(code):
	path = adapter_paths().get(code)
	if not path:
		raise PermanentError(f"No ASP adapter registered for '{code}'")
	return load_class(path)


def get_adapter(connection):
	"""Instantiate the adapter for an ASP Connection (document or name)."""
	import frappe

	from thinknxg_einvoice_hub.core.connections import connection_config

	doc = frappe.get_doc("ASP Connection", connection) if isinstance(connection, str) else connection
	if not doc.enabled:
		raise PermanentError(f"ASP Connection {doc.name} is disabled")
	return get_adapter_class(doc.asp_provider)(connection_config(doc))
