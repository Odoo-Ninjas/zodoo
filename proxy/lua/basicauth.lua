local _M = {}

-- Hilfsfunktion: base64-Kodierung mit ngx API
local function b64_encode(str)
    return ngx.encode_base64(str)
end


-- basicauth(username, password)
function _M.basicauth(username, password)
    -- Erwarteten Header aufbauen
    local expected = "Basic " .. b64_encode(username .. ":" .. password)

    -- Header auslesen (nil -> Leerstring)
    local auth = ngx.var.http_authorization or ""

    if auth ~= expected then
        -- Browser zum Login-Dialog auffordern
        ngx.header["WWW-Authenticate"] = 'Basic realm="Restricted"'
        return ngx.exit(ngx.HTTP_UNAUTHORIZED)  -- 401
    end

end

return _M
