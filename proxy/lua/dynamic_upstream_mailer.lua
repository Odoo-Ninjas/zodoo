local myngx = require("myngx")
local hostname = "roundcube"
local port = "80"
local varname = "target_mailer"

if os.getenv("RUN_MAIL") == "1" then
    local ip = myngx.get_ip(hostname)

    if ip then
        ngx.var[varname] = "http://" .. ip .. ":" .. port
    end
end