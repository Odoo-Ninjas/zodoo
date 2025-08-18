local myngx = require("myngx")
local hostname = "roundcube"
local port = "80"
local varname = "target_mailer"
ngx.log(ngx.INFO, "Running dynamic_upstream_mailer.lua with default target: " .. ngx.var['default_target'])

if os.getenv("RUN_MAIL") == "1" then
    ngx.log(ngx.INFO, "RUN_MAIL=1")
    local ip = myngx.get_ip(hostname)

    if ip then
        ngx.var[varname] = "http://" .. ip .. ":" .. port
    end
end
