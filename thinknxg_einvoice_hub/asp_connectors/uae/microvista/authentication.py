"""Authentication for Microvista.

The scheme is not public. Whatever Microvista documents (API key, OAuth2, HMAC ...)
is selected in the ASP REST API Configuration and executed by the generic engine;
this module only reports whether enough has been configured to try.
"""


def is_configured(rest):
	auth = (rest or {}).get("auth") or {}
	kind = auth.get("type") or "None"
	if kind == "None":
		return False
	needs = {
		"API Key": ("api_key",), "Bearer Token": ("api_secret",), "Basic": ("username", "password"),
		"OAuth2 Client Credentials": ("client_id", "client_secret", "token_url"),
		"OAuth2 Authorization Code": ("client_id", "client_secret", "refresh_token"),
		"HMAC-SHA256": ("api_secret",), "JWT": ("api_secret",), "Custom Header": (), "Plugin": ("plugin",),
	}.get(kind, ())
	return all(auth.get(field) for field in needs) or bool(auth.get("static_authorization_header"))
