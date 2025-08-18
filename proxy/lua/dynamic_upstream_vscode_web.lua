local myngx = require("myngx")
local hostname = "vscode"
local port = "8080"
local varname = "target_webvscode"

ngx.log(ngx.INFO, "Redirecting to vscode")

if os.getenv("RUN_VSCODE") == "1" then
    local ip = myngx.get_ip(hostname)
    if ip then
        ngx.var[varname] = "http://" .. ip .. ":" .. port
    end
end
