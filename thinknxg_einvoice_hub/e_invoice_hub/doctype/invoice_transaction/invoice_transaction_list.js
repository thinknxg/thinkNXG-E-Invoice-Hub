frappe.listview_settings["Invoice Transaction"] = {
	add_fields: ["status", "direction"],
	get_indicator(doc) {
		const colors = {
			Received: "blue",
			Normalized: "blue",
			Validated: "cyan",
			"Validation Failed": "orange",
			Submitted: "yellow",
			Delivered: "green",
			Rejected: "red",
			Retrying: "orange",
			Failed: "red",
			Duplicate: "gray",
			Cancelled: "gray",
		};
		return [__(doc.status), colors[doc.status] || "gray", `status,=,${doc.status}`];
	},
};
