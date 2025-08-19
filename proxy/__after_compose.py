import yaml
import json
import base64

import inspect
import os
from pathlib import Path
current_dir = Path(os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe()))))

def after_compose(config, settings, yml, globals):
    if 'proxy_abstract' in yml['services']:
        yml['services'].pop('proxy_abstract')


    collect_proxy_config(yml)

def collect_proxy_config(yml):
    proxy_backends = {}
    for service_name, service in yml['services'].items():
        if not service.get("build"):
            continue
        buildcontext = Path(service['build']['context'])
        proxy_configs = buildcontext / "_proxy"
        if not proxy_configs.exists():
            continue

        for file in proxy_configs.glob("*"):
            if not file.is_file():
                continue
            conf_name = file.name
            conf_content = file.read_text(encoding='utf-8')
            line = conf_content.splitlines()[0]
            clean = line.lstrip("/ ").strip()
            # split on ':'
            _, value = clean.split(":", 1)   # proxy_host: roundcube:80 -> ["proxy_host", " roundcube:80"]
            host, port = value.strip().split(":")
            proxy_backends[service_name] = {
                "host": host.strip(),
                "port": int(port.strip()),
                "nginx_conf": conf_content.strip() + "\n"
            }

    proxy_backends_encoded = base64.b64encode(
        json.dumps(proxy_backends).encode('utf-8')
    ).decode('utf-8')

    yml['services']['proxy']['environment']['PROXY_BACKENDS'] = proxy_backends_encoded