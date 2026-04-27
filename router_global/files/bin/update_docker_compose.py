#!/usr/bin/env python3
"""
Input: Network name 

Adds following snippet to the docker-compose:

services:
    ...
    networks:
      - default
      - network_abc

networks:
  network_abc:
    name: network_abc
    external: true
"""
from pathlib import Path
import yaml
import sys

if len(sys.argv) == 1:
    raise Exception("Requires network")

dcfile = Path('docker-compose.yml')
config = yaml.safe_load(dcfile.read_text())
ttype = sys.argv[1]
if ttype == "-n":
  network_name = sys.argv[2]
  config['services']['router']['networks'].append(network_name)
  config.setdefault('networks', {})
  config['networks'][network_name] = {
      'name': network_name,
      'external': True
  }
elif ttype == "-v":
  volume = sys.argv[2]
  config['services']['router'].setdefault('volumes', [])
  config['services']['router']['volumes'].append(volume)

dcfile.write_text(yaml.dump(config))