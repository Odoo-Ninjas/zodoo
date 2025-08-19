import yaml
import json
import base64

def after_compose(config, settings, yml, globals):
    if 'proxy_abstract' in yml['services']:
        yml['services'].pop('proxy_abstract')

    proxy_backends = {
        "mail": {
            "host": "roundcube",
            "port": 80,
            "nginx_conf": """

            }
            """
        },
    }
    proxy_backends_encoded = base64.b64encode(
        json.dumps(proxy_backends).encode('utf-8')
    ).decode('utf-8')

    yml['services']['proxy']['environment']['PROXY_BACKENDS'] = proxy_backends_encoded