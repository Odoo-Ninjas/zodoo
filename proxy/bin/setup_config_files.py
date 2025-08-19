#!/usr/bin/env python3
import os
from pathlib import Path

# Example JSON/dict input (replace with json.load if reading from file)
proxy_backends = {
    "mail": {
        "host": "roundcube",
        "port": 80,
        "nginx_conf": """
            location /mailer {{
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
            }}
        """
    },
}

# Directories from ENV with fallback defaults
LUA_DIR = Path(os.environ.get("LUA_DIR", "/usr/local/openresty/nginx/lua"))
CONF_DIR = Path(os.environ.get("CONF_DIR", "/usr/local/openresty/nginx/conf.d"))
LUA_TEMPLATE = Path(os.environ['LUA_TEMPLATE']).read_text()

# Ensure dirs exist
LUA_DIR.mkdir(parents=True, exist_ok=True)
CONF_DIR.mkdir(parents=True, exist_ok=True)

for name, cfg in proxy_backends.items():
    host = cfg["host"]
    port = cfg["port"]
    conf = cfg["nginx_conf"]

    # Lua file
    lua_filename = LUA_DIR / f"dynamic_upstream_{name}.lua"
    with open(lua_filename, "w") as f:
        f.write(LUA_TEMPLATE.format(hostname=host, port=port))

    # Nginx conf file
    conf_filename = CONF_DIR / f"{name}.conf"
    with open(conf_filename, "w") as f:
        conf_content = conf.format(lua_resolve_host=lua_filename)
        f.write(conf_content.strip() + "\n")

    print(f"Generated {lua_filename} and {conf_filename}")