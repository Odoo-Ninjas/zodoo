local myngx = require("myngx")
local hostname = "{hostname}"
local port = "{port}"

local ip = myngx.get_ip(hostname)

if ip then
    ngx.var['backend'] = "http://" .. ip .. ":" .. port
end