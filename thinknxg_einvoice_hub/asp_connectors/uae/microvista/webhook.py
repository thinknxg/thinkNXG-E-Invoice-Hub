"""Webhooks from Microvista.

Event names, payload shape and the signature scheme are not public (checklist MV-12).
Verification and parsing therefore run entirely from the webhook section of the ASP
REST API Configuration. Unsigned requests are always rejected.
"""
