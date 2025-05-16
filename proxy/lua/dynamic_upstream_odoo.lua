local incoming_headers = ngx.req.get_headers()
local request_proto = incoming_headers["X-Forwarded-Proto"] or "http"  -- default fallback
ngx.req.set_header("X-Forwarded-Proto", request_proto)


local myngx = require("myngx")
local projectname = os.getenv("PROJECT_NAME")
local hostname = "odoo"
if projectname then
    hostname = projectname .. "_" .. "odoo"
end
local varname = "target_odoo"
local port1 = "8069"
local port2 = "8072"

local ip = myngx.get_ip(hostname)
ngx.log(ngx.INFO, "Checking upstream odoo: " .. hostname .. " - " .. tostring(ip))

if ip then
    local backend = "http://" .. ip .. ":" .. port1
    local backend_chat = "http://" .. ip .. ":" .. port2

    ngx.var[varname] = backend
    ngx.var[varname .. "chat"] = backend_chat
end

ngx.log(ngx.INFO, "Done with upstream odoo check: " .. ngx.var[varname])