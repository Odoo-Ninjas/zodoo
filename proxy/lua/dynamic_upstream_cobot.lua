local myngx = require("myngx")
local hostname = "novnc_cobot"
local port = "6080"
local varname = "target_cobot"

if os.getenv("RUN_ROBOT") == "1" then
    local ip = myngx.get_ip(hostname)
    if ip then
        ngx.var[varname] = "http://" .. ip .. ":" .. port
    end
end

