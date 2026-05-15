#!/usr/bin/env python3
"""
Input: 
* fluentd host with port e.g. 10.250.0.5:24224
* fluentd tag


Appends:
logging:
    driver: "fluentd"
    options:
        fluentd-address: "localhost:24224"
        tag: httpd.access
"""
from pathlib import Path
import yaml
import sys

if len(sys.argv) == 1:
    raise Exception("Requires network")

dcfile = Path('docker-compose.yml')
config = yaml.safe_load(dcfile.read_text())
for service in config['services']:
    service = config['services'][service]
    service.setdefault('logging', {})
    service['logging'] = {
        "driver": "fluentd",
        "options": {
        'fluentd-address': sys.argv[1],
        'tag': sys.argv[2],
        }
    }
dcfile.write_text(yaml.dump(config))