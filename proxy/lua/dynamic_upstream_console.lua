proxy/lua/dynamic_upstream_odoo.lualocal myngx = require("myngx")
local varname = "target_console"
local websshhost = os.getenv("WEBSSH_CONSOLE_HOST") -- "http://webssh:8080"
local devmode = os.getenv("DEVMODE")

if not websshhost or devmode ~= "1" then
    ngx.log(ngx.INFO, 'WEBSSH not configured. Turn on RUN_CONSOLE please.')

else
    ngx.log(ngx.INFO, 'WEBSSH Host is: ' .. websshhost)

    local hostname, port = websshhost:match("^https?://([^:/]+):?(%d*)")

    local ip = myngx.get_ip(hostname)
    if ip then
        ngx.var[varname] = "http://" .. ip .. ":" .. port;
    end
    ngx.log(ngx.INFO, varname .. ":", ngx.var[varname])
end
