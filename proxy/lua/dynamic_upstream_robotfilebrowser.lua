local myngx = require("myngx")
local hostname = "robot_file_browser"
local port = "80"
local varname = "target_robotfilebrowser"

if os.getenv("RUN_ROBOT") == "1" then
    local ip = myngx.get_ip(hostname)
    if ip then
        ngx.var[varname] = "http://" .. ip .. ":" .. port
    end
end
