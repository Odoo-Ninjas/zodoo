local myngx = require("myngx")
local hostname = "seleniumdriver"
local port = "7900"
local varname = "target_robotlive"

ngx.log(ngx.INFO, "Redirecting to seleniumdriver vnc")

if os.getenv("RUN_ROBOT") == "1" then
    local ip = myngx.get_ip(hostname)
    if ip then
        ngx.var[varname] = "http://" .. ip .. ":" .. port
    end
end

