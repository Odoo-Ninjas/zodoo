The backup server no longer issues a repository key, and an offsite run no longer needs one. `odoo offsite register` now receives an upload account plus the two age **public** keys, so a machine set up this way holds **no secret that can read its own backup** — public keys encrypt and decrypt nothing.

This closes the last gap of the restic arrangement, where the passphrase had to sit on the source machine because deduplication needs the encrypted repository index. A compromised Odoo host could therefore read every older state of its own backup; now there is nothing on it to read them with.

It also makes the handover much less delicate: the access password is replaceable (`restic-area passwd`), so losing it costs a new password rather than a backup. The only irreplaceable secrets are the private age keys, and those are never created on the server — they live in the password vault. An older backup server that still issues `repo_url`/`repo_key` keeps working unchanged.
