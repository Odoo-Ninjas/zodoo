local myngx = require("myngx")
local hostname = "selenium_vncviewer"
local port = "5900"
local varname = "target_selenium_xpra"

ngx.log(ngx.INFO, "Redirecting to selenium_xpra")

if os.getenv("RUN_ROBOT") == "1" then
    local ip = myngx.get_ip(hostname)
    if ip then
        ngx.var[varname] = "http://" .. ip .. ":" .. port
    end
end

