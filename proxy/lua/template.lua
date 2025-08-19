local incoming_headers = ngx.req.get_headers()
local request_proto = 
    incoming_headers["x-forwarded-proto"]
    or ngx.var.http_x_forwarded_proto   -- Nginx var (if set by previous hop)
    or "http"
ngx.req.set_header("x-forwarded-proto", request_proto)

local projectname = os.getenv("PROJECT_NAME")
local myngx = require("myngx")
local hostname = "{hostname}"
local port = "{port}"


if projectname then
    hostname = projectname .. "_" .. "odoo"
end

local ip = myngx.get_ip(hostname)

if ip then
    ngx.var['backend'] = "http://" .. ip .. ":" .. port
end