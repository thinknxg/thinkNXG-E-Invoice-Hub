"""Pagero adapter placeholder. See PlannedASPAdapter."""

from thinknxg_einvoice_hub.asp_connectors.base_adapter import PlannedASPAdapter


class PageroAdapter(PlannedASPAdapter):
	code = "pagero"
	label = "Pagero"
	description = "Dedicated adapter pending provider API onboarding. Connect via the Generic REST adapter meanwhile."
