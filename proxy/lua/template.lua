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
local ip = myngx.get_ip(hostname)

local user = "{auth_user}"
local pass_var = "{auth_pass}"

-- authorization section
ngx.log(ngx.ERR, "\nPass var:'" .. pass_var .. "' not set")
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
