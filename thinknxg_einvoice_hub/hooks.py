app_name = "thinknxg_einvoice_hub"
app_title = "thinkNXG E-Invoice Hub"
app_publisher = "Kreatao"
app_description = "Universal e-invoicing integration platform: any ERP, any accredited service provider, one canonical invoice."
app_license = "mit"

add_to_apps_screen = [
	{
		"name": "thinknxg_einvoice_hub",
		"logo": "/assets/thinknxg_einvoice_hub/images/einvoice-hub.svg",
		"title": "thinkNXG E-Invoice Hub",
		"route": "/app/thinknxg-e-invoice-hub",
		"has_permission": "thinknxg_einvoice_hub.install.has_app_permission",
	}
]

before_install = "thinknxg_einvoice_hub.install.before_install"
after_install = "thinknxg_einvoice_hub.install.after_install"
after_migrate = "thinknxg_einvoice_hub.install.after_migrate"

# ---------------------------------------------------------------- tenant isolation
_TENANT_DOCTYPES = [
	"Integration Tenant",
	"ERP Connection",
	"ASP Connection",
	"Company Integration Profile",
	"Mapping Configuration",
	"Invoice Transaction",
	"Invoice Payload",
	"Webhook Event",
	"Integration Audit Log",
	"Integration Log",
	"ASP REST API Configuration",
	"Microvista Settings",
]
permission_query_conditions = {
	dt: "thinknxg_einvoice_hub.core.tenant_manager.get_permission_query_conditions" for dt in _TENANT_DOCTYPES
}
has_permission = {dt: "thinknxg_einvoice_hub.core.tenant_manager.has_permission" for dt in _TENANT_DOCTYPES}

# ---------------------------------------------------------------- scheduler
scheduler_events = {
	"cron": {
		"*/5 * * * *": ["thinknxg_einvoice_hub.services.retry_service.run_due_retries"],
		"*/10 * * * *": ["thinknxg_einvoice_hub.services.reconciliation.poll_erp_connections"],
		"*/15 * * * *": [
			"thinknxg_einvoice_hub.services.reconciliation.sync_submitted_statuses",
			"thinknxg_einvoice_hub.services.reconciliation.poll_incoming_invoices",
		],
	},
	"hourly": ["thinknxg_einvoice_hub.services.reconciliation.retry_erp_sync"],
	"daily": ["thinknxg_einvoice_hub.core.integration_log.purge_old_logs"],
}

# ---------------------------------------------------------------- extension points
# Other apps contribute connectors, adapters and country engines through these hooks:
#   einvoice_hub_erp_connectors      = {"<code>": "<dotted.path.ConnectorClass>"}
#   einvoice_hub_asp_adapters        = {"<code>": "<dotted.path.AdapterClass>"}
#   einvoice_hub_compliance_engines  = {"<code>": "<dotted.path.EngineClass>"}
#   einvoice_hub_rest_transformations = {"<name>": "<dotted.path.function(value, arg)>"}
#   einvoice_hub_rest_auth_plugins    = {"<name>": "<dotted.path.function(...) -> headers>"}
