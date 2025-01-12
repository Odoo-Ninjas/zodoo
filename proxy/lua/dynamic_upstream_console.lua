local myngx = require("myngx")
local varname = "target_console"
local websshhost = os.getenv("WEBSSH_HOST") -- "http://webssh:8080"

local hostname, port = websshhost:match("^https?://([^:/]+):?(%d*)")


local ip = myngx.get_ip(hostname)
if ip then
    ngx.var[varname] = "http://" .. ip .. ":" .. port;
end
ngx.log(ngx.INFO, varname .. ":", ngx.var[varname])