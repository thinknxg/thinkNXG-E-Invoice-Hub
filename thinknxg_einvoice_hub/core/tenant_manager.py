"""Tenant isolation.

Every tenant-scoped record carries a ``tenant`` link. Users only ever see
records of the tenants they are listed on (Integration Tenant > Users); hub
administrators see everything. Enforced three ways: list queries
(``permission_query_conditions``), document access (``has_permission``) and
explicit checks in the API layer.
"""

import frappe
from frappe import _

ADMIN_ROLES = {"System Manager", "E-Invoice Hub Admin"}
TENANT_SCOPED = (
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
)
#: doctypes where an empty tenant means "shared, read-only for tenants"
SHARED_WHEN_EMPTY = ("Mapping Configuration", "ASP REST API Configuration")


def is_hub_admin(user=None):
	user = user or frappe.session.user
	return user == "Administrator" or bool(ADMIN_ROLES.intersection(frappe.get_roles(user)))


def get_user_tenants(user=None):
	user = user or frappe.session.user
	cache = getattr(frappe.local, "_eih_user_tenants", None)
	if cache is None:
		cache = frappe.local._eih_user_tenants = {}
	if user not in cache:
		names = frappe.get_all(
			"Integration Tenant User",
			filters={"user": user, "parenttype": "Integration Tenant"},
			pluck="parent",
		)
		active = frappe.get_all("Integration Tenant", filters={"name": ["in", names], "status": "Active"},
			pluck="name") if names else []
		cache[user] = active
	return cache[user]


def get_permission_query_conditions(user=None, doctype=None):
	user = user or frappe.session.user
	if is_hub_admin(user):
		return ""
	tenants = get_user_tenants(user)
	if doctype == "Integration Tenant":
		column = "`tabIntegration Tenant`.`name`"
	else:
		column = f"`tab{doctype}`.`tenant`"
	parts = []
	if tenants:
		parts.append(f"{column} in ({', '.join(frappe.db.escape(t) for t in tenants)})")
	if doctype in SHARED_WHEN_EMPTY:
		parts.append(f"ifnull({column}, '') = ''")
	return f"({' or '.join(parts)})" if parts else "1=0"


def has_permission(doc, ptype=None, user=None):
	user = user or frappe.session.user
	if is_hub_admin(user):
		return True
	tenant = doc.name if doc.doctype == "Integration Tenant" else doc.get("tenant")
	if not tenant:
		# new unsaved records pass here and are checked in validate(); shared templates are read-only
		if doc.is_new():
			return True
		return doc.doctype in SHARED_WHEN_EMPTY and ptype in (None, "read", "select", "report", "export", "print")
	return tenant in get_user_tenants(user)


def assert_tenant_access(tenant, user=None):
	if not tenant or not (is_hub_admin(user) or tenant in get_user_tenants(user)):
		frappe.throw(_("You do not have access to this tenant"), frappe.PermissionError)


def require_access(tenant, *levels, user=None):
	"""Require one of the given access levels (Admin / User / API) on the tenant; hub admins always pass."""
	user = user or frappe.session.user
	if is_hub_admin(user):
		return
	assert_tenant_access(tenant, user)
	access = frappe.db.get_value(
		"Integration Tenant User",
		{"parent": tenant, "parenttype": "Integration Tenant", "user": user},
		"access",
	)
	if access not in levels:
		frappe.throw(_("Your access level on this tenant does not allow this action"), frappe.PermissionError)


def validate_tenant_on_doc(doc):
	"""Called from tenant-scoped controllers: users may only write into their own tenants."""
	if is_hub_admin():
		return
	if not doc.get("tenant"):
		frappe.throw(_("Tenant is required"))
	assert_tenant_access(doc.tenant)


def assert_same_tenant(doc, fieldname, doctype, allow_shared=False):
	"""A link on a tenant-scoped record must point to a record of the same tenant."""
	target = doc.get(fieldname)
	if not target:
		return
	other = frappe.db.get_value(doctype, target, "tenant")
	if other == doc.tenant or (allow_shared and not other):
		return
	frappe.throw(_("{0} {1} belongs to a different tenant").format(_(doctype), target))


def resolve_api_tenant(tenant=None):
	"""Tenant for the current API caller. ``tenant`` may be a name or tenant code."""
	user = frappe.session.user
	if tenant:
		name = tenant if frappe.db.exists("Integration Tenant", tenant) else frappe.db.get_value(
			"Integration Tenant", {"tenant_code": tenant}, "name")
		if not name:
			frappe.throw(_("Unknown tenant"), frappe.PermissionError)
		assert_tenant_access(name, user)
		return name
	tenants = get_user_tenants(user)
	if len(tenants) == 1:
		return tenants[0]
	if not tenants:
		frappe.throw(_("This user is not assigned to any tenant"), frappe.PermissionError)
	frappe.throw(_("This user belongs to several tenants; pass the 'tenant' parameter"))
