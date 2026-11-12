"""Microvista adapter: a selectable provider that runs on a verified, configured API contract."""

from thinknxg_einvoice_hub.asp_connectors.generic_rest.configured import ContractPendingAdapter
from thinknxg_einvoice_hub.asp_connectors.uae.microvista import (
	authentication,
	config,
	credit_note,
	invoice_builder,
	purchase_invoice,
	sales_invoice,
)
from thinknxg_einvoice_hub.asp_connectors.uae.microvista.exceptions import MicrovistaContractPending


class MicrovistaAdapter(ContractPendingAdapter):
	code = config.PROVIDER_CODE
	label = "Microvista"
	status = "Development"
	website = config.WEBSITE
	provider_name = config.PROVIDER_NAME
	legal_name = config.LEGAL_NAME
	accreditation_number = config.ACCREDITATION_NUMBER
	description = ("Dedicated adapter skeleton. Pending Microvista's official API documentation and sandbox "
		"credentials; not production-ready.")

	def _require_configuration(self):
		report = self.readiness()
		if not report["ready_for_sandbox"]:
			raise MicrovistaContractPending(
				"Microvista is not ready to transmit: " + "; ".join(report["blocking"])
				+ ". See docs/MICROVISTA_SETUP.md."
			)

	def readiness(self):
		"""What is configured and what still blocks sandbox testing. Never contacts the provider."""
		rest = self.rest or {}
		endpoints = rest.get("endpoints") or {}
		configured = [op for op in endpoints if self.engine.has_operation(rest, op)]
		blocking = []
		if not rest:
			blocking.append("no ASP REST API Configuration is attached to the connection")
		if not rest.get("base_url"):
			blocking.append("base URL for the selected environment is missing (MV-01)")
		if not authentication.is_configured(rest):
			blocking.append("authentication is not configured (MV-02)")
		for operation in config.REQUIRED_OPERATIONS:
			if operation not in configured:
				blocking.append(f"endpoint '{operation}' is not configured")
		if "Submit Invoice" in configured and not any(
			r.get("target") == "asp_document_id" for r in rest.get("response_mappings") or []
		):
			blocking.append("response mapping for 'asp_document_id' is missing (MV-07)")
		return {
			"provider": config.LEGAL_NAME,
			"accreditation_number": config.ACCREDITATION_NUMBER,
			"integration_status": config.INTEGRATION_STATUS,
			"ready_for_sandbox": not blocking,
			"production_ready": False,  # set only after sandbox tests pass against the real API
			"blocking": blocking,
			"configured_operations": configured,
			"missing_recommended": [op for op in config.RECOMMENDED_OPERATIONS if op not in configured],
			"checklist": [{"id": i, "item": text, "where": where} for i, text, where in config.API_CHECKLIST],
		}

	def submit_invoice(self, payload, metadata):
		return sales_invoice.submit(self, invoice_builder.build(payload, metadata), metadata)

	def submit_document(self, payload, metadata):
		return self.submit_invoice(payload, metadata)

	def submit_credit_note(self, payload, metadata):
		return credit_note.submit(self, invoice_builder.build(payload, metadata), metadata)

	def get_incoming_invoices(self, since=None):
		return purchase_invoice.fetch(self, since)
