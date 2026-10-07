DEVMODE: the mail servers that turn-into-dev redirects to the local mail
catcher are renamed to "Test-Mailserver (<old name>)", so a dev copy is no
longer mistaken for the live mail service. Translated (jsonb) names are
prefixed in every language; running turn-into-dev again does not stack the
prefix. The outgoing mail servers are now also redirected when fetchmail is
not installed (Odoo 13-16).
