Base image builds no longer break when Odoo's upstream `requirements.txt`
pins a version that has since been **yanked** from PyPI. Previously `pip
install` aborted with "No matching distribution found" (e.g.
`cbor2==5.4.2`), failing the base image build for every project sitting on
the affected Odoo pin.

`lib_base_image` now rewrites known-yanked pins to the nearest safe release
via a small `_YANKED_PIN_OVERRIDES` table (seeded with `cbor2 5.4.2 ->
5.4.6`, which is what upstream Odoo itself moved to) right where the
framework requirements are read. The rewritten text is what gets both
hashed and installed, so the base image rebuilds automatically once an
override is added — no need to bump the whole Odoo submodule pin.

Only an exact `name==version` pin is rewritten; markers, comments and
neighbouring pins (including `cbor2==5.4.2.post1`) stay untouched.
