-- Password-only auth gate for the monitoring dashboard.
--
-- HTTP basic auth always forces a username field, which is awkward when there
-- is only a single shared secret. This gate instead serves a minimal
-- password-only login page, sets a signed cookie on success and lets every
-- following request through. The shared password is read at request time from
-- the DASHBOARD_PASSWORD env var (empty -> gate disabled, e.g. in DEVMODE).
--
-- Wired from dashboard.conf via:
--     rewrite_by_lua_block { require("dashauth").gate(os.getenv("DASHBOARD_PASSWORD")) }
-- The rewrite phase runs before access_by_lua_file (backend resolution), so an
-- unauthenticated request never reaches Grafana.
--
-- A second argument makes the gate reusable for other areas that share the
-- same shape -- one secret, no user name. coding.conf passes "/code" so the
-- browser editor is not open to the internet. Each area gets its own cookie
-- and its own login path, so the password for one does not open the other.

local _M = {}

-- Cookie carries an HMAC of the password (never the password itself), so it
-- cannot be reused once the password changes and is opaque to the client.
local SECRET = "zodoo-dashboard-gate"
local DEFAULT_BASE = "/system"

-- Cookie and login path are derived from the guarded area, so /system and
-- /code cannot be unlocked with each other's cookie.
local function area(base_path)
    local base = base_path or DEFAULT_BASE
    local name = base:gsub("^/", ""):gsub("[^%w_]", "_")
    return base, "zodoo_gate_" .. name, base .. "/__auth"
end

local function token(password, cookie)
    -- The cookie name goes into the HMAC: without it the same password would
    -- yield the same value everywhere, and one area's cookie would unlock the
    -- next.
    return ngx.encode_base64(ngx.hmac_sha1(SECRET, cookie .. ":" .. password))
end

-- Constant-time string comparison (avoid leaking length/prefix via timing).
local bit = require("bit")
local function const_eq(a, b)
    if type(a) ~= "string" or type(b) ~= "string" then
        return false
    end
    if #a ~= #b then
        return false
    end
    local diff = 0
    for i = 1, #a do
        diff = bit.bor(diff, bit.bxor(a:byte(i), b:byte(i)))
    end
    return diff == 0
end

local function login_page(msg, titel, auth_path)
    local err = ""
    if msg then
        err = '<p class="err">' .. msg .. "</p>"
    end
    return [[<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>]] .. titel .. [[</title><style>
body{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;
background:#111217;font-family:system-ui,-apple-system,sans-serif;color:#d8d9da}
form{background:#1f2128;padding:34px 30px;border-radius:10px;width:280px;
box-shadow:0 8px 30px rgba(0,0,0,.55);text-align:center}
h1{font-size:16px;font-weight:600;margin:0 0 20px}
input{width:100%;box-sizing:border-box;padding:11px 12px;margin-bottom:14px;
border:1px solid #383a42;border-radius:6px;background:#0f1015;color:#fff;font-size:14px}
input:focus{outline:none;border-color:#f60}
button{width:100%;padding:11px;border:0;border-radius:6px;background:#f60;
color:#fff;font-size:14px;font-weight:600;cursor:pointer}
button:hover{background:#ff7a1a}
.err{color:#ff6b6b;font-size:13px;margin:0 0 12px}
</style></head><body><form method="POST" action="]] .. auth_path .. [[">
<h1>&#128274; ]] .. titel .. [[</h1>]] .. err .. [[
<input type="password" name="password" placeholder="Passwort" autofocus>
<button type="submit">Anmelden</button></form></body></html>]]
end

local function serve_login(status, msg, auth_path, titel)
    ngx.status = status
    ngx.header.content_type = "text/html; charset=utf-8"
    ngx.header["Cache-Control"] = "no-store"
    ngx.say(login_page(msg, titel, auth_path))
    return ngx.exit(status)
end

function _M.gate(password, base_path, titel)
    if not password or password == "" then
        return -- no password configured -> gate disabled (open)
    end
    local base, cookie, auth_path = area(base_path)
    titel = titel or ("zodoo " .. base:gsub("^/", ""))
    local expected = token(password, cookie)

    -- Login form submit.
    if ngx.var.uri == auth_path then
        if ngx.var.request_method ~= "POST" then
            return ngx.redirect(base)
        end
        ngx.req.read_body()
        local args = ngx.req.get_post_args() or {}
        if const_eq(args.password, password) then
            ngx.header["Set-Cookie"] = cookie
                .. "="
                .. expected
                .. "; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000"
            return ngx.redirect(base)
        end
        return serve_login(
            ngx.HTTP_UNAUTHORIZED, "Falsches Passwort", auth_path, titel
        )
    end

    -- Already authenticated via cookie?
    if const_eq(ngx.var["cookie_" .. cookie], expected) then
        return
    end

    -- Otherwise show the password page.
    return serve_login(ngx.HTTP_UNAUTHORIZED, nil, auth_path, titel)
end

return _M
