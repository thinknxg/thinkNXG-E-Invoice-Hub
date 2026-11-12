frappe.ui.form.on("Invoice Transaction", {
	refresh(frm) {
		const status = frm.doc.status;
		const api = "thinknxg_einvoice_hub.api.status";
		const run = (method, args, message) =>
			frappe.call({ method: `${api}.${method}`, args: { transaction: frm.doc.name, ...args } }).then(() => {
				frappe.show_alert({ message, indicator: "green" });
				setTimeout(() => frm.reload_doc(), 1500);
			});

		if (["Received", "Normalized", "Validated", "Validation Failed", "Retrying", "Failed"].includes(status)) {
			frm.add_custom_button(__("Reprocess"), () => run("reprocess", { renormalize: 1 }, __("Queued for processing")));
			frm.add_custom_button(__("Cancel Transaction"), () =>
				frappe.confirm(__("Stop processing this transaction?"), () => run("cancel", {}, __("Cancelled")))
			);
		}
		if (status === "Submitted") {
			frm.add_custom_button(__("Refresh ASP Status"), () => run("refresh_status", {}, __("Status refreshed")));
		}
		frm.add_custom_button(
			__("Payloads"),
			() => frappe.set_route("List", "Invoice Payload", { transaction: frm.doc.name }),
			__("View")
		);
		frm.add_custom_button(
			__("Audit Trail"),
			() => frappe.set_route("List", "Integration Audit Log", { transaction: frm.doc.name }),
			__("View")
		);
	},
});
