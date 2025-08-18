local resolver = require "resty.dns.resolver"
local favicon_dev = "http://127.0.0.1:8080/favicon_dev.png"
local favicon_default = "http://127.0.0.1:8080/favicon_default.ico"

-- Resolve the hostname dynamically
local r, err = resolver:new({
    nameservers = {"127.0.0.11"}, -- Docker's DNS resolver
    retrans = 5,
    timeout = 2000, -- 2 seconds timeout
})

if not r then
    ngx.log(ngx.ERR, "Failed to instantiate the resolver: ", err)
    ngx.exit(ngx.HTTP_INTERNAL_SERVER_ERROR)
end
local answers, err = r:query("odoo") -- Replace "odoo" with your service hostname
if not answers then
    ngx.log(ngx.ERR, "Failed to query the DNS server: ", err)
    ngx.exit(ngx.HTTP_SERVICE_UNAVAILABLE)
end
if answers.errcode then
    ngx.log(ngx.ERR, "DNS server returned error code: ", answers.errcode, ": ", answers.errstr)
    ngx.exit(ngx.HTTP_SERVICE_UNAVAILABLE)
end

local ip
for _, ans in ipairs(answers) do
    if ans.address then
        ip = ans.address
        break
    end
end


if not ip then
    ngx.var.target_favicon = favicon_default
    ngx.log(ngx.WARN, "No valid IP address found for 'odoo'; using backup")
    return
end

local backend = "http://" .. ip .. ":8069"

if os.getenv("DEVMODE") == "1" then
    ngx.var.target_favicon = favicon_dev
else
    ngx.var.target_favicon = backend .. "/web/static/img/favicon.ico"
end
