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

local _M = {}

-- Cookie carries an HMAC of the password (never the password itself), so it
-- cannot be reused once the password changes and is opaque to the client.
local SECRET = "zodoo-dashboard-gate"
local COOKIE = "zodoo_dash_auth"
local AUTH_PATH = "/system/__auth"

local function token(password)
    return ngx.encode_base64(ngx.hmac_sha1(SECRET, password))
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

local function login_page(msg)
    local err = ""
    if msg then
        err = '<p class="err">' .. msg .. "</p>"
    end
    return [[<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>zodoo dashboard</title><style>
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
</style></head><body><form method="POST" action="]] .. AUTH_PATH .. [[">
<h1>&#128274; zodoo dashboard</h1>]] .. err .. [[
<input type="password" name="password" placeholder="Passwort" autofocus>
<button type="submit">Anmelden</button></form></body></html>]]
end

local function serve_login(status, msg)
    ngx.status = status
    ngx.header.content_type = "text/html; charset=utf-8"
    ngx.header["Cache-Control"] = "no-store"
    ngx.say(login_page(msg))
    return ngx.exit(status)
end

function _M.gate(password)
    if not password or password == "" then
        return -- no password configured -> gate disabled (open)
    end
    local expected = token(password)

    -- Login form submit.
    if ngx.var.uri == AUTH_PATH then
        if ngx.var.request_method ~= "POST" then
            return ngx.redirect("/system")
        end
        ngx.req.read_body()
        local args = ngx.req.get_post_args() or {}
        if const_eq(args.password, password) then
            ngx.header["Set-Cookie"] = COOKIE
                .. "="
                .. expected
                .. "; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000"
            return ngx.redirect("/system")
        end
        return serve_login(ngx.HTTP_UNAUTHORIZED, "Falsches Passwort")
    end

    -- Already authenticated via cookie?
    if const_eq(ngx.var["cookie_" .. COOKIE], expected) then
        return
    end

    -- Otherwise show the password page (no Grafana login involved).
    return serve_login(ngx.HTTP_UNAUTHORIZED, nil)
end

return _M
