"""Submit Credit Note for Microvista (runs the configured operation)."""

OPERATION = "Submit Credit Note"


def submit(adapter, payload, metadata):
	from thinknxg_einvoice_hub.asp_connectors.generic_rest.configured import ConfiguredRestAdapter

	return ConfiguredRestAdapter._submit(adapter, OPERATION, payload, metadata)
