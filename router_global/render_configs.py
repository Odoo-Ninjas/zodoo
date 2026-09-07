#!/usr/bin/env python3
"""Render all nginx vhost configs in one shot.

Usage: render_configs.py <templates_dir> <output_dir>
Reads virtual_hosts list as JSON from stdin.
"""

import json
import pathlib
import re
import sys

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from jinja2.exceptions import UndefinedError

templates_dir, output_dir = sys.argv[1], sys.argv[2]
virtual_hosts = json.load(sys.stdin)

# StrictUndefined: without it a missing field renders as an empty string and
# we silently write a broken nginx config - "server :;", "proxy_pass http://$var_;",
# "proxy_connect_timeout ;". Optional fields are all guarded with
# "is defined" in the templates, so only genuinely missing ones fail here.
env = Environment(
    loader=FileSystemLoader(templates_dir),
    undefined=StrictUndefined,
    keep_trailing_newline=False,
    trim_blocks=True,
    lstrip_blocks=False,
)

out = pathlib.Path(output_dir)
out.mkdir(parents=True, exist_ok=True)

for host in virtual_hosts:
    tpl = env.get_template(host["template"])
    try:
        rendered = tpl.render(item=host)
    except UndefinedError as ex:
        # Name the vhost and the field - a bare jinja message says neither.
        field = re.search(r"has no attribute '([^']+)'", str(ex))
        missing = field.group(1) if field else str(ex)
        sys.exit(
            f"vhost '{host.get('server_name', '?')}' "
            f"(template '{host['template']}'): field '{missing}' is missing.\n"
            f"See router_global/vhosts.example.yml for the fields each "
            f"template needs."
        )
    filename = host.get("filename", host["server_name"])
    (out / filename).write_text(rendered)
