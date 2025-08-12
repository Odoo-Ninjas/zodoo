#!/bin/bash
# Install dependencies
set -ex

# Install latest Python and Robot Framework
whoami
python3 -mvenv /opt/robotcode
. /opt/robotcode/bin/activate
pip install -r /opt/robot.requirements.txt
