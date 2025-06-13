FROM ubuntu:24.04
ARG  relpathname
ARG  APT_PROXY_IP

ENV DEBIAN_FRONTEND=noninteractive
ENV NOVNC_TAG="v1.5.0"

ENV WEBSOCKIFY_TAG="v0.12.0"

ENV VNC_SERVER="localhost:5900"

#___SNIPPET_APT_PROXY___

RUN #___SNIPPET_APT_INSTALL___ \
        bash \
        python3 \
        python3-dev \
        gfortran \
        python3-pip \
        build-essential \
        procps \
        git \
        rsync \ 
        libffi-dev

RUN apt-get install -y python3-venv
RUN python3 -mvenv /venv
RUN /venv/bin/pip install --no-cache-dir numpy

RUN git config --global advice.detachedHead false && \
    git clone https://github.com/novnc/noVNC --branch ${NOVNC_TAG} /root/noVNC

#RUN sed -i "/wait ${proxy_pid}/i if [ -n \"\$AUTOCONNECT\" ]; then sed -i \"s/'autoconnect', false/'autoconnect', '\$AUTOCONNECT'/\" /root/noVNC/app/ui.js; fi" /root/noVNC/utils/novnc_proxy

#RUN sed -i "/wait ${proxy_pid}/i if [ -n \"\$VNC_PASSWORD\" ]; then sed -i \"s/WebUtil.getConfigVar('password')/'\$VNC_PASSWORD'/\" /root/noVNC/app/ui.js; fi" /root/noVNC/utils/novnc_proxy

#RUN sed -i "/wait ${proxy_pid}/i if [ -n \"\$VIEW_ONLY\" ]; then sed -i \"s/UI.rfb.viewOnly = UI.getSetting('view_only');/UI.rfb.viewOnly = \$VIEW_ONLY;/\" /root/noVNC/app/ui.js; fi" /root/noVNC/utils/novnc_proxy

RUN sed -i "s|\"app|\"/$relpathname/app|g" /root/noVNC/vnc.html
RUN cp /root/noVNC/vnc.html /root/noVNC/index.html


RUN python3 <<EOF
# make available for sub path
from pathlib import Path
import subprocess
import os

source = Path("/root/noVNC")
dest = Path("/root/noVNC") / os.getenv("relpathname")
dest.mkdir(exist_ok=True, parents=True)
print(f"copying from {source} to {dest}")
subprocess.check_call(["rsync", str(source) + "/", str(dest) + "/", "-ar"])
EOF

RUN mkdir /root/websockify
WORKDIR /root/websockify
ENTRYPOINT [ "bash", "-c", ". /venv/bin/activate && ./run --web /root/noVNC --token-plugin TokenFileName --token-source $TOKEN_FILE 6080 " ]