"""Incoming (purchase) documents from Microvista.

Whether Microvista delivers incoming invoices by polling, webhook or both is not
public (checklist MV-11). Both routes are wired to configuration.
"""

OPERATION = "Get Incoming Invoices"


def fetch(adapter, since=None):
	from thinknxg_einvoice_hub.asp_connectors.generic_rest.configured import ConfiguredRestAdapter

	return ConfiguredRestAdapter.get_incoming_invoices(adapter, since)
