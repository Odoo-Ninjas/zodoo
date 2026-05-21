local incoming_headers = ngx.req.get_headers()
local request_proto =
    incoming_headers["x-forwarded-proto"]
    or ngx.var.http_x_forwarded_proto   -- Nginx var (if set by previous hop)
    or "http"
ngx.req.set_header("x-forwarded-proto", request_proto)

local myngx = require("myngx")
local basicauth = require("basicauth")
local hostname = "{hostname}"
local port = "{port}"
local odoo_update = false
local ip = ""

-- lua flags managed in nginx.conf - http
local dict = ngx.shared.flags

-- =========================================================================
-- Warmup gate: while odoo/bin/tools.py:set_warmup_in_progress() has touched
-- /var/proxy_exchange/warmup_in_progress, hold API requests inside the proxy
-- and show browsers a maintenance page with auto-refresh. The flag flips
-- back to false within ~1s after the odoo container clears the sentinel in
-- _signal_warmup_done(). No-op when the standalone-deployment never set
-- the sentinel in the first place.
-- =========================================================================
-- NOTE: template.lua is substituted via Python str.format() in
-- proxy/bin/setup_config_files.py. Every literal opening or closing
-- brace below must be doubled (open-open / close-close) so the
-- formatter passes them through. This applies to the JSON error body
-- and the CSS in the maintenance page — and to this comment, which is
-- why it uses words rather than the brace characters themselves.
if dict:get("warmup_in_progress") then
    local accept = ngx.var.http_accept or ""
    local uri    = ngx.var.uri or ""
    local is_api = string.find(uri, "^/jsonrpc")
                or string.find(uri, "^/xmlrpc")
                or string.find(uri, "^/web/dataset")
                or string.find(uri, "^/longpolling")
                or string.find(uri, "^/websocket")
                or string.find(uri, "^/bus/")
                or not string.find(accept, "text/html", 1, true)

    if is_api then
        local max_hold_s = tonumber(os.getenv("WARMUP_PROXY_HOLD_S")) or 120
        local poll_s     = 0.5
        local waited     = 0
        while waited < max_hold_s do
            ngx.sleep(poll_s)
            waited = waited + poll_s
            if not dict:get("warmup_in_progress") then
                break  -- fall through to normal proxy logic below
            end
        end
        if dict:get("warmup_in_progress") then
            -- Hold-Timeout überschritten — sauberer 503 statt
            -- Connection-Drop.
            ngx.status = 503
            ngx.header["Retry-After"] = "5"
            ngx.header["Content-Type"] = "application/json"
            ngx.say('{{"error":"service starting — hold exceeded ' .. max_hold_s .. 's"}}')
            return ngx.exit(503)
        end
    else
        -- Browser: Wartungsseite mit Auto-Refresh. Generisch — kein
        -- Branding-Leak. Alle "open-open"/"close-close" Klammern unten
        -- werden von Python str.format() zu single braces zurückgesetzt.
        ngx.status = 503
        ngx.header["Retry-After"] = "3"
        ngx.header["Content-Type"] = "text/html; charset=utf-8"
        ngx.say([[<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<title>Just a moment…</title>
<meta http-equiv="refresh" content="3">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{{color-scheme:light dark}}
*{{box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;
  margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
  background:#f5f6f8;color:#1f2937}}
@media (prefers-color-scheme: dark){{body{{background:#0f1115;color:#e5e7eb}}}}
.card{{max-width:420px;padding:48px 32px;text-align:center}}
.spinner{{width:48px;height:48px;margin:0 auto 24px;
  border:3px solid rgba(127,127,127,0.18);
  border-top-color:#3b82f6;
  border-radius:50%;
  animation:spin 0.9s linear infinite}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
h1{{font-size:1.25rem;font-weight:600;margin:0 0 8px}}
p{{font-size:0.95rem;opacity:0.7;margin:0;line-height:1.5}}
</style>
</head><body>
<div class="card">
  <div class="spinner" aria-hidden="true"></div>
  <h1>Just a moment</h1>
  <p>We're getting things ready. This page will reload automatically.</p>
</div>
</body></html>]])
        return ngx.exit(503)
    end
end

local odoo_update = dict:get("odoo_update")

if odoo_update then
    hostname = "proxy"
    port = "3333"
    ip = myngx.get_ip(hostname)
else

    -- insert: if cookie exists - "debugpython=1" then set hostname to "odoo_debug"
    -- but only if port is 8069(str)
    local cookie = ngx.var.http_cookie
    if cookie and port == "8069" then
        -- find() returns the index if substring exists, or nil otherwise
        if string.find(cookie, "debugpython=1", 1, true) then
            ngx.log(ngx.INFO, "debugpython cookie detected — using odoo_debug")
            hostname = "odoo_debug"
        end
    end

    ip = myngx.get_ip(hostname)

    local user = "{auth_user}"
    local pass_var = "{auth_pass}"

    -- authorization section
    if pass_var and pass_var ~= "" then
        -- Lookup environment variable by that name
        local pass = os.getenv(pass_var)
        if pass and pass ~= "" then
            -- Run auth
            basicauth.basicauth(user, pass)
        end
    else
        ngx.log(ngx.INFO, "No auth_pass set, skipping basicauth()")
    end
end

-- If hostname is already a URL, just use it as-is
if ip and ip ~= "" then
    ngx.var['backend'] = "http://" .. ip .. ":" .. port
end
