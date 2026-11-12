"""Avalara adapter placeholder. See PlannedASPAdapter."""

from thinknxg_einvoice_hub.asp_connectors.base_adapter import PlannedASPAdapter


class AvalaraAdapter(PlannedASPAdapter):
	code = "avalara"
	label = "Avalara"
	description = "Dedicated adapter pending provider API onboarding. Connect via the Generic REST adapter meanwhile."
