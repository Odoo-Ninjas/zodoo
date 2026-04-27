`odoo build` now passes `TARGETARCH` explicitly as a build-arg so that prebuilt Python image references (`zodoo/python:<ver>-<arch>`) resolve correctly when `COMPOSE_BAKE=true` is active.
