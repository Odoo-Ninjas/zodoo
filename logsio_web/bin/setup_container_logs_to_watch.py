#!/usr/bin/env python3
"""

Gets the logs path of given container names and enters them into configuration input file

"""

import os
import json
import docker as Docker
from pathlib import Path

docker = Docker.from_env()

# reset configuration file
config_file = Path(os.environ["LOGIO_FILE_INPUT_CONFIG_PATH"])
config = json.loads(config_file.read_text())
config["inputs"] = []

project_name = os.environ["project_name"]
containers = docker.containers.list(all=True, filters={"name": [project_name]})
for container in containers:
    path = Path(f"/var/lib/docker/containers/{container.id}")
    config["inputs"].append(
        {
            "stream": project_name,
            "source": container.name,
            "config": {
                "path": str(path / "*.log"),
                "watcherOptions": {"ignored": "*.txt", "depth": 2},
            },
        }
    )
config_file.write_text(json.dumps(config))
