While the Odoo web container is warming up (asset pre-gen + per-worker
HTTP cache fill), the bundled nginx proxy now blocks external traffic:
browsers receive a 503 with `Retry-After` and an auto-refreshing
maintenance page, while API clients (JSON-RPC, XML-RPC, JSON-Accept
header, longpolling/websocket/bus) are **held inside the proxy** via
`ngx.sleep` until warmup finishes and then transparently forwarded to
Odoo — no client-side retry needed. Hold timeout configurable via
`WARMUP_PROXY_HOLD_S` (default 120 s). Internal warmup probes hit
`localhost:8069` and bypass the proxy. In standalone deployments without
the zodoo proxy (e.g. AWS, custom reverse-proxy) the touch silently
falls back to a warning — the warmup runs unchanged.
