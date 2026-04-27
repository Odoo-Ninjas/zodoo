#!/usr/bin/env python3
"""Render all nginx vhost configs in one shot.

Usage: render_configs.py <templates_dir> <output_dir>
Reads virtual_hosts list as JSON from stdin.
"""
import json
import pathlib
import sys

from jinja2 import Environment, FileSystemLoader, StrictUndefined

templates_dir, output_dir = sys.argv[1], sys.argv[2]
virtual_hosts = json.load(sys.stdin)

env = Environment(
    loader=FileSystemLoader(templates_dir),
    keep_trailing_newline=False,
    trim_blocks=True,
    lstrip_blocks=False,
)

out = pathlib.Path(output_dir)
out.mkdir(parents=True, exist_ok=True)

for host in virtual_hosts:
    tpl = env.get_template(host["template"])
    rendered = tpl.render(item=host)
    (out / host["server_name"]).write_text(rendered)
