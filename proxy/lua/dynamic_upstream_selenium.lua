local myngx = require("myngx")
local hostname = "seleniumvnc"
local port = "5900"
local varname = "target_seleniumvnc"

ngx.log(ngx.INFO, "Redirecting to seleniumvnc")

if os.getenv("RUN_ROBOT") == "1" then
    local ip = myngx.get_ip(hostname)
    if ip then
        ngx.var[varname] = "http://" .. ip .. ":" .. port
    end
end

