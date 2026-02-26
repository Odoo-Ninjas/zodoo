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

-- insert: if cookie exists - "debugpython=1" then set hostname to "odoo_debug"
-- but only if port is 8069(str)
local cookie = ngx.var.http_cookie
if cookie and port == "8069" then
    -- find() returns the index if substring exists, or nil otherwise
    if string.find(cookie, "debugpython=1") then
        ngx.log(ngx.INFO, "debugpython cookie detected — using odoo_debug")
        hostname = "odoo_debug"
    end
end

local port = "{port}"

local ip = myngx.get_ip(hostname)

local user = "{auth_user}"
local pass_var = "{auth_pass}"

-- authorization section
if pass_var and pass_var ~= "" then
    -- Lookup environment variable by that name
    local pass = os.getenv(pass_var)
    if pass ~= "" then
        -- Run auth
        basicauth.basicauth(user, pass)
    end
else
    ngx.log(ngx.INFO, "No auth_pass set, skipping basicauth()")
end

-- If hostname is already a URL, just use it as-is
if ip then
    ngx.var['backend'] = "http://" .. ip .. ":" .. port
end

-- das sollte man sehen
