"""0.1.x -> 0.2.0: derive the independent lifecycle fields for transactions created before they existed.

Earlier versions tracked one overall status. Nothing is known about FTA reporting for those
documents, so ``fta_status`` stays "Not Applicable"; delivery and ASP acceptance follow the old status.
"""

import frappe

RULES = (
	# old overall status -> (validation_status, asp_submission_status, delivery_status)
	("Delivered", "Passed", "Accepted", "Delivered"),
	("Submitted", "Passed", "Submitted", "Pending"),
	("Rejected", "Passed", "Rejected", None),
	("Validated", "Passed", None, None),
	("Validation Failed", "Failed", None, None),
)


def execute():
	table = frappe.qb.DocType("Invoice Transaction")
	for status, validation, submission, delivery in RULES:
		query = frappe.qb.update(table).set(table.validation_status, validation).where(table.status == status)
		query = query.where(table.direction == "Outbound") if submission else query
		if submission:
			query = query.set(table.asp_submission_status, submission)
		if delivery:
			query = query.set(table.delivery_status, delivery)
		query.run()
	# inbound documents that reached the hub were validated; they have no ASP submission of their own
	frappe.qb.update(table).set(table.validation_status, "Passed").where(table.direction == "Inbound").where(
		table.status.isin(["Validated", "Delivered"])).run()
