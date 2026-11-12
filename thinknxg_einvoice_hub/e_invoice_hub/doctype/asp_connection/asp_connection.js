frappe.ui.form.on("ASP Connection", {
	refresh(frm) {
		thinknxg_einvoice_hub_connection_refresh(frm, "asp");
	},
});

function thinknxg_einvoice_hub_connection_refresh(frm, kind) {
	if (frm.is_new()) {
		frm.fields_dict.webhook_help.$wrapper.html(
			`<p class="text-muted">${__("Save the connection to see its webhook URL.")}</p>`
		);
		return;
	}
	const url = `${window.location.origin}/api/method/thinknxg_einvoice_hub.api.webhooks.${kind}?connection=${encodeURIComponent(frm.doc.name)}`;
	frm.fields_dict.webhook_help.$wrapper.html(
		`<p><code>${frappe.utils.escape_html(url)}</code></p>
		<p class="text-muted">${__(
			"Sign the raw request body with HMAC-SHA256 using the webhook secret and send the hex digest in the X-EIH-Signature header."
		)}</p>`
	);
	frm.add_custom_button(__("Test Connection"), () => {
		frm.call("test_connection").then((r) => {
			const ok = (r.message || "").startsWith("Success");
			frappe.show_alert({ message: r.message, indicator: ok ? "green" : "red" }, 8);
			frm.reload_doc();
		});
	});
}
