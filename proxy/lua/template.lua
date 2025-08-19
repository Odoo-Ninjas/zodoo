local incoming_headers = ngx.req.get_headers()
local request_proto = 
    incoming_headers["x-forwarded-proto"]
    or ngx.var.http_x_forwarded_proto   -- Nginx var (if set by previous hop)
    or "http"
ngx.req.set_header("x-forwarded-proto", request_proto)

local myngx = require("myngx")
local hostname = "{hostname}"
local port = "{port}"
local ip = myngx.get_ip(hostname)

-- If hostname is already a URL, just use it as-is
if string.sub(hostname, 1, 7) == "http://" or string.sub(hostname, 1, 8) == "https://" then
    ngx.var['backend'] = hostname
else
    local ip = myngx.get_ip(hostname)
    if ip then
        ngx.var['backend'] = "http://" .. ip .. ":" .. port
    end
end