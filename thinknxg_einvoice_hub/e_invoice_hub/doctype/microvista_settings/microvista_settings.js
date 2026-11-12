frappe.ui.form.on("Microvista Settings", {
	refresh(frm) {
		const box = frm.fields_dict.readiness_html.$wrapper;
		if (frm.is_new()) {
			box.html(`<p class="text-muted">${__("Save to see what is still needed before sandbox testing.")}</p>`);
			return;
		}
		const esc = frappe.utils.escape_html;
		frm.call("get_readiness").then((r) => {
			const d = r.message || {};
			const blocking = (d.blocking || []).map((b) => `<li>${esc(b)}</li>`).join("");
			const checklist = (d.checklist || [])
				.map((c) => `<tr><td>${esc(c.id)}</td><td>${esc(c.item)}</td><td class="text-muted">${esc(c.where)}</td></tr>`)
				.join("");
			box.html(`
				<p><b>${esc(d.provider || "")}</b> &middot; ${__("Accreditation number")} ${esc(d.accreditation_number || "")}
				&middot; ${esc(d.integration_status || "")}</p>
				<p>${d.ready_for_sandbox
					? `<span class="indicator-pill green">${__("Ready for sandbox testing")}</span>`
					: `<span class="indicator-pill orange">${__("Not ready to transmit")}</span>`}
				<span class="indicator-pill red">${__("Not production verified")}</span></p>
				${blocking ? `<p>${__("Blocking items")}</p><ul>${blocking}</ul>` : ""}
				<p>${__("API details to obtain from the provider's official documentation")}</p>
				<table class="table table-bordered table-sm"><tbody>${checklist}</tbody></table>`);
		});
		frm.add_custom_button(__("Verify Credentials"), () => {
			frm.call("verify_credentials").then((r) => {
				const ok = (r.message || "").startsWith("Success");
				frappe.msgprint({ message: esc(r.message || ""), indicator: ok ? "green" : "orange", title: __("Microvista") });
				frm.reload_doc();
			});
		});
	},
});
