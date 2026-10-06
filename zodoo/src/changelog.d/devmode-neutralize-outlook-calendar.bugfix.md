A DEVMODE restore of an Odoo 19 database now cuts the Outlook calendar
sync. The users' Microsoft access and refresh tokens are cleared, the sync
is marked as stopped for every user and the Microsoft client secrets
(`microsoft_calendar_client_secret`, `microsoft_outlook_client_secret`) are
deleted - the same as Odoo's own `microsoft_calendar/data/neutralize.sql`,
plus the secrets. Before, a dev copy kept the real refresh tokens; a sync
from there wrote into real Outlook calendars and Outlook sent the
invitations. Databases without the Microsoft modules are unaffected.
