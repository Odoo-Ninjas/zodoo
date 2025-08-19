#!/usr/bin/env python3
import re
import os
import base64
import json
from pathlib import Path

# Example JSON/dict input (replace with json.load if reading from file)
proxy_backends = json.loads(base64.b64decode(os.environ.get("PROXY_BACKENDS", "{}")))
sample = """
# proxy_host: odoo:8069
# proxy_host: os.getenv("PROXY_ODOO_HOST") or "odoo:8069"
location /mailer {
    rewrite ^/mailer$ /mailer/ break;
    set $backend $default_target;
    access_by_lua_file "{lua_resolve_host}";
    proxy_pass $backend;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    # proxy_set_header X-Forwarded-Path /mailer/;

    error_page 502 503 504 = @fallback;
}
"""

def parse_host_port(value):
    """Parse 'host:port' into (host, port) strings."""
    host, port = value.split(":", 1)
    return host.strip(), port.strip()

PROXY_LINE_RE = re.compile(r'^\s*#proxy_host:\s*(.+?)\s*$', re.IGNORECASE | re.MULTILINE)
def resolve_proxy_host(backend):
    if backend.get('external'):
        return backend['external'], None
    config  = backend['nginx_conf']
    m = PROXY_LINE_RE.search(config)
    if not m:
        return None, None
    expr = m.group(1).strip()
    # Otherwise treat as literal
    host, port = parse_host_port(expr)
    host = os.getenv("project_name") + "_" + host
    return host, port

# Directories from ENV with fallback defaults
LUA_DIR = Path(os.environ.get("LUA_DIR", "/usr/local/openresty/nginx/lua"))
CONF_DIR = Path(os.environ.get("CONF_DIR", "/usr/local/openresty/nginx/conf.d"))
LUA_TEMPLATE = Path(os.environ['LUA_TEMPLATE']).read_text()

# Ensure dirs exist
LUA_DIR.mkdir(parents=True, exist_ok=True)
CONF_DIR.mkdir(parents=True, exist_ok=True)

for name, cfg in proxy_backends.items():
    print("Processing backend:", name)
    host, port = resolve_proxy_host(cfg)
    if not host:
        continue

    lua_filename = None
    if not cfg.get('external'):
        # Lua file
        lua_filename = LUA_DIR / f"dynamic_upstream_{name}.lua"
        with open(lua_filename, "w") as f:
            f.write(LUA_TEMPLATE.format(hostname=host, port=port))

    # Nginx conf file
    conf_filename = CONF_DIR / f"{name}.conf"
    conf = cfg['nginx_conf']
    with open(conf_filename, "w") as f:
        if lua_filename:
            conf = conf.replace("{lua_resolve_host}", str(lua_filename))
        f.write(conf.strip() + "\n")

    print(f"Generated {lua_filename or '<no luafilename because external host>'} and {conf_filename}")
