frappe.ui.form.on("ASP REST API Configuration", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Verify Credentials"), () => {
			frm.call("verify_credentials").then((r) => {
				const ok = (r.message || "").startsWith("Success");
				frappe.msgprint({ message: frappe.utils.escape_html(r.message || ""), indicator: ok ? "green" : "red",
					title: __("Verify Credentials") });
			});
		});
		frm.add_custom_button(__("Integration Logs"), () =>
			frappe.set_route("List", "Integration Log", { operation: ["is", "set"] })
		);
		frm.set_intro(
			__("Endpoints entered here are only as reliable as the documentation they came from. Keep the provider in " +
				"the directory at its true integration status until sandbox tests have passed."),
			"blue"
		);
	},
});
