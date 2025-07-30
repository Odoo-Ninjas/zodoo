local myngx = {}
local resolver = require "resty.dns.resolver"

function myngx.get_ip(hostname)
	local dns_server = os.getenv("PROXY_DNS_SERVER")
	
	ngx.log(ngx.INFO, "Resolving ip address for " .. hostname .. " using DNS server: " .. dns_server)
	local ip
	local r, err = resolver:new({
		nameservers = {dns_server}, -- Docker's DNS resolver
		retrans = 5,
		timeout = 2000, -- 2 seconds timeout
	})

	if not r then
		ngx.log(ngx.ERR, "Failed to instantiate the resolver: ", err)
		ngx.exit(ngx.HTTP_INTERNAL_SERVER_ERROR)
	end

	local answers, err = r:query(hostname) -- Replace "odoo" with your service hostname

	if not answers then
		ngx.log(ngx.ERR, "Failed to query the DNS server: ", err)
		ngx.exit(ngx.HTTP_SERVICE_UNAVAILABLE)
	end

	if answers.errcode then
		ngx.log(ngx.ERR, "DNS server returned error code: ", answers.errcode, ": ", answers.errstr)
		ngx.exit(ngx.HTTP_SERVICE_UNAVAILABLE)
	end

	for _, ans in ipairs(answers) do
		if ans.address then
			ip = ans.address
			break
		end
	end

	if not ip then
		ngx.log(ngx.WARN, "No valid IP address found for " .. hostname .. "; using backup")
		return nil
	end

	ngx.log(ngx.INFO, "Found IP address for " .. hostname .. ": " .. ip)

	return ip
end

return myngx