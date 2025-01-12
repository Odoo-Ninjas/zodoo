local myngx = require("myngx")
local hostname = "odoo"
local varname = "target_odoo"
local port1 = "8069"
local port2 = "8072"

local ip = myngx.get_ip(hostname)

if ip then
    local backend = "http://" .. ip .. ":" .. port1
    local backend_chat = "http://" .. ip .. ":" .. port2

    ngx.var[varname] = backend
    ngx.var[varname .. "chat"] = backend_chat
end
