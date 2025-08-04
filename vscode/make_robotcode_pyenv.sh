#!/bin/bash
# Install dependencies
set -ex


# Install pyenv
curl https://pyenv.run | bash

# Add to path
export PYENV_ROOT="/home/user1/.pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init -)"
eval "$(pyenv virtualenv-init -)"

# Install latest Python and Robot Framework
pyenv install 3.12.3
pyenv virtualenv 3.12.3 robotcode
pyenv activate robotcode
pip install -r /opt/robot.requirements.txt