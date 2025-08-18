local myngx = require("myngx")
local hostname = "logs"
local port = "6688"
local varname = "target_logs"

if os.getenv("DEVMODE") == "1" then
    local ip = myngx.get_ip(hostname)
    if ip then
        ngx.var[varname] = "http://" .. ip .. ":" .. port
    end
end
