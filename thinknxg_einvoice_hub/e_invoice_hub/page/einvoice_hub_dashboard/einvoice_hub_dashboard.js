frappe.pages["einvoice-hub-dashboard"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Universal Integration Dashboard"),
		single_column: true,
	});
	const filters = {};
	const add = (df) => {
		filters[df.fieldname] = page.add_field({ ...df, change: () => refresh() });
	};
	add({
		fieldname: "country", label: __("Country"), fieldtype: "Select",
		options: [{ value: "", label: __("All countries") }, { value: "AE", label: __("UAE") },
			{ value: "OM", label: __("Oman") }],
	});
	add({ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company Integration Profile" });
	add({ fieldname: "erp_connection", label: __("ERP"), fieldtype: "Link", options: "ERP Connection" });
	add({ fieldname: "asp_connection", label: __("ASP"), fieldtype: "Link", options: "ASP Connection" });
	add({ fieldname: "from_date", label: __("From"), fieldtype: "Date" });
	add({ fieldname: "to_date", label: __("To"), fieldtype: "Date" });
	add({
		fieldname: "document_type", label: __("Invoice Type"), fieldtype: "Select",
		options: ["", "INVOICE", "CREDIT_NOTE", "SELF_BILLING_INVOICE", "SELF_BILLING_CREDIT_NOTE"],
	});
	add({
		fieldname: "status", label: __("Transaction Status"), fieldtype: "Select",
		options: ["", "Received", "Normalized", "Validated", "Validation Failed", "Submitted", "Delivered",
			"Reported", "Rejected", "Retrying", "Failed", "Cancelled", "Duplicate"],
	});
	add({
		fieldname: "fta_status", label: __("Tax Authority Reporting"), fieldtype: "Select",
		options: ["", "Not Applicable", "Pending", "Reported", "Rejected"],
	});
	add({
		fieldname: "delivery_status", label: __("Delivery"), fieldtype: "Select",
		options: ["", "Not Applicable", "Pending", "Delivered", "Failed"],
	});

	const body = $('<div class="einvoice-hub-dashboard" style="padding: var(--padding-md)"></div>').appendTo(page.main);
	const esc = frappe.utils.escape_html;

	const card = (label, value, color, route) => `
		<div class="col-sm-6 col-md-3" style="margin-bottom: var(--margin-md)">
			<div class="frappe-card" style="padding: var(--padding-md); ${route ? "cursor:pointer" : ""}"
				${route ? `data-route='${esc(JSON.stringify(route))}'` : ""}>
				<div class="text-muted small">${esc(label)}</div>
				<div style="font-size: 24px; font-weight: 600; color: var(--${color || "text-color"})">${esc(String(value ?? 0))}</div>
			</div>
		</div>`;
	const section = (title, cards) => `<h6 class="text-muted uppercase" style="margin: var(--margin-md) 0">${esc(title)}</h6>
		<div class="row">${cards.join("")}</div>`;

	function refresh() {
		const args = {};
		Object.keys(filters).forEach((k) => {
			const v = filters[k].get_value();
			if (v) args[k] = v;
		});
		frappe.call({ method: "thinknxg_einvoice_hub.services.monitoring.get_dashboard", args }).then((r) => {
			const d = r.message || {};
			const c = d.connections || {};
			const i = d.invoices || {};
			const t = "Invoice Transaction";
			body.html(
				section(__("Connections"), [
					card(__("ERP connections"), c.erp_total, null, ["List", "ERP Connection", {}]),
					card(__("Active ERP connections"), c.erp_active, "green-600", ["List", "ERP Connection", { enabled: 1 }]),
					card(__("Configured ASP connections"), c.asp_configured, null, ["List", "ASP Connection", { enabled: 1 }]),
					card(__("Production-verified ASPs"), `${c.asp_production_ready ?? 0} / ${c.asp_in_directory ?? 0}`, null,
						["List", "UAE Accredited Service Provider", {}]),
				]) +
				section(__("Invoices"), [
					card(__("Received"), i.received, null, ["List", t, {}]),
					card(__("Validated"), i.validated, "green-600", ["List", t, { validation_status: "Passed" }]),
					card(__("Submitted to ASP"), i.submitted, null, ["List", t, { asp_submission_status: ["!=", "Not Submitted"] }]),
					card(__("ASP accepted"), i.asp_accepted, "green-600", ["List", t, { asp_submission_status: "Accepted" }]),
					card(__("ASP rejected"), i.asp_rejected, "red-600", ["List", t, { asp_submission_status: "Rejected" }]),
					card(__("Tax authority: reported"), i.fta_reported, "green-600", ["List", t, { fta_status: "Reported" }]),
					card(__("Tax authority: pending acknowledgement"), i.fta_pending, "orange-600", ["List", t, { fta_status: "Pending" }]),
					card(__("Tax authority: rejected"), i.fta_rejected, "red-600", ["List", t, { fta_status: "Rejected" }]),
					card(__("Peppol delivered"), i.delivered, "green-600", ["List", t, { delivery_status: "Delivered" }]),
					card(__("Delivery failures"), i.delivery_failed, "red-600", ["List", t, { delivery_status: "Failed" }]),
					card(__("Validation failures"), i.validation_failed, "orange-600", ["List", t, { status: "Validation Failed" }]),
				]) +
				section(__("Attention"), [
					card(__("Pending ERP synchronization"), i.pending_sync, "orange-600",
						["List", t, { erp_sync_status: ["in", ["Pending", "Failed"]] }]),
					card(__("Retry queue"), i.retry_queue, "orange-600", ["List", t, { status: "Retrying" }]),
					card(__("Failed transactions"), i.failed, "red-600", ["List", t, { status: "Failed" }]),
					card(__("Failed API calls"), d.api_failures, "red-600", ["List", "Integration Log", { result: "Failure" }]),
				]) +
				section(__("By country"), Object.entries(d.by_country || {}).map(([code, n]) =>
					card(code === "OM" ? __("Oman") : code === "AE" ? __("UAE") : code, n, null,
						["List", t, code === "Unassigned" ? { country_code: ["is", "not set"] } : { country_code: code }]))) +
				`<p class="text-muted small">${esc(__("Internal validation, provider submission, tax authority reporting and Peppol delivery are separate statuses. A submission accepted by the provider is not proof of tax authority reporting or delivery."))}</p>`
			);
			body.find("[data-route]").on("click", function () {
				const route = JSON.parse($(this).attr("data-route"));
				frappe.set_route(route[0], route[1], route[2]);
			});
		});
	}

	page.set_primary_action(__("Refresh"), refresh, "refresh");
	refresh();
};
