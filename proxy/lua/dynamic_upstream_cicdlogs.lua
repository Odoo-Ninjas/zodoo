local myngx = require("myngx")
local hostname = "cicdlogs"
local port = "6688"
local varname = "target_cicdlogs"

local ip = myngx.get_ip(hostname)
if ip then
    ngx.var[varname] = "http://" .. ip .. ":" .. port
end
