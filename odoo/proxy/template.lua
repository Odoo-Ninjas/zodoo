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
            ngx.say('{"error":"odoo warming up — hold exceeded ' .. max_hold_s .. 's"}')
            return ngx.exit(503)
        end
    else
        -- Browser: Wartungsseite mit Auto-Refresh.
        ngx.status = 503
        ngx.header["Retry-After"] = "3"
        ngx.header["Content-Type"] = "text/html; charset=utf-8"
        ngx.say([[<!doctype html><html><head>
<title>Warming up…</title>
<meta http-equiv="refresh" content="3">
<style>body{font-family:system-ui,sans-serif;max-width:520px;margin:8em auto;padding:0 1em;color:#444}
h1{font-weight:600}.spin{display:inline-block;animation:s 1s linear infinite}
@keyframes s{to{transform:rotate(360deg)}}</style>
</head><body>
<h1><span class="spin">&#9203;</span> Odoo is warming up</h1>
<p>This usually takes a few seconds. The page will reload automatically.</p>
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
