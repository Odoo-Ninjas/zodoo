

local proxy_odoo_host = os.getenv("PROXY_ODOO_HOST")
local hostname = "odoo"
if proxy_odoo_host then
    hostname = proxy_odoo_host
elseif projectname then
end
