import json
import base64

import inspect
import os
from pathlib import Path

current_dir = Path(
    os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
)


def after_compose(config, settings, yml, globals):
    if "proxy_abstract" in yml["services"]:
        yml["services"].pop("proxy_abstract")

    globals["load_proxy_backends"] = _load_backends
    globals["apply_proxy_backends"] = _apply_backends

    collect_proxy_config(yml)


def collect_proxy_config(yml):
    proxy_backends = _load_backends(yml)
    for service_name, service in yml["services"].items():
        if service.get("labels", {}).get("proxy_config") == "0":
            continue

        if service_name in proxy_backends:
            continue

        files = {}
        for label, content in service.get("labels", {}).items():
            if label.startswith("proxy_config"):
                suffix = label.replace("proxy_config", "")

                lua_template = service.get("labels", {}).get(
                    "proxy_lua_template", ""
                )
                if lua_template and Path(lua_template).exists():
                    lua_template = Path(lua_template).read_text()
                else:
                    lua_template = ""

                data = {
                    "nginx_conf_file": Path(content),
                    "lua_template": lua_template,
                }
                files[service_name + suffix] = data
        for upstream_name, data in files.items():
            nginx_conf_file = Path(data["nginx_conf_file"])
            if not nginx_conf_file.is_file():
                continue
            conf_content = nginx_conf_file.read_text(encoding="utf-8")
            proxy_backends[upstream_name] = {
                "nginx_conf": conf_content.strip() + "\n",
                "lua_template": data.get("lua_template", ""),
            }

    _apply_backends(yml, proxy_backends)


def _load_backends(yml):
    backends = yml["services"]["proxy"]["environment"].get(
        "PROXY_BACKENDS", {}
    )
    if backends:
        backends = json.loads(base64.b64decode(backends))
    return backends


def _apply_backends(yml, backends):
    backends = base64.b64encode(json.dumps(backends).encode("utf-8")).decode(
        "utf-8"
    )

    yml["services"]["proxy"]["environment"]["PROXY_BACKENDS"] = backends
