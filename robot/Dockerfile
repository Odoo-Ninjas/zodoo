FROM ubuntu:22.04 AS builder
ARG TARGETARCH

ENV DEBIAN_FRONTEND=noninteractive
ENV WORKDIR=/opt/robot
ENV ROBOT_THREADS=1
ENV PATH="$PATH:/opt/robot/.local/bin"



#___SNIPPET_APT_PROXY___

RUN #___SNIPPET_APT_INSTALL___ \
wget unzip python3 python3.10 \
python3-pip python3-magic libmagickwand-dev curl \
sudo pipx build-essential python3-dev python3.10-dev \
gnupg-agent git gosu net-tools rsync ssh ca-certificates gnupg lsb-release ncdu

COPY ./requirements.txt /tmp/requirements.txt
RUN python3 -mpip install -U pip
RUN python3 -mpip install $(cat /etc/pip_options) setuptools python-dotenv
RUN python3 -mpip install $(cat /etc/pip_options) -r /tmp/requirements.txt
RUN rm -rf /tmp/requirements.txt


WORKDIR $WORKDIR

RUN useradd -rm -s /bin/bash -d /opt/robot -g root -G sudo robot
RUN echo 'robot ALL=NOPASSWD:SETENV: ALL' > /etc/sudoers.d/robot

#___SNIPPET_DOCKER___


USER root
#___SNIPPET_ZODOO___

RUN mkdir -p /opt/robot/.local && chown robot /opt/robot /opt/robot/.local
USER robot
RUN pip install setuptools==65.6.0 --break-system-packages
RUN mkdir -p /opt/robot/.ssh && \
chmod 500 /opt/robot/.ssh
#--------------------------------------------
USER root

#RUN find /opt/robot -not -user robot -exec chown robot {} \; >/dev/null 2>&1
COPY ssh_config /opt/robot/.ssh/config
RUN chown robot /opt/robot/.ssh/config


# hadolint ignore=DL3002
USER root

# ###########################
# Scripties
RUN touch /opt/robot/.hushlogin
COPY robotest.py ./
COPY entrypoint.sh ./
RUN chmod a+x entrypoint*.sh
COPY set_docker_group.sh /usr/local/bin/set_docker_group.sh

# replace opencv-python (GUI) with headless variant (saves ~80 MB)
RUN python3.10 -mpip uninstall -y opencv-python opencv-python-headless 2>/dev/null; \
rm -rf /usr/local/lib/python3.10/dist-packages/opencv_python*.libs \
/usr/local/lib/python3.10/dist-packages/opencv_python*.dist-info \
/usr/local/lib/python3.10/dist-packages/cv2 && \
python3.10 -mpip install --no-cache-dir opencv-python-headless

# cleanup in builder so the final COPY gets clean files
RUN apt-get purge -y build-essential gcc g++ libpq-dev python3-dev || true && \
apt-get autoremove -y || true && \
apt-get clean -y || true && \
rm -rf /var/lib/apt/lists/* /var/lib/dpkg /tmp/* /var/tmp/* /var/log/* \
/usr/share/doc /usr/share/man /usr/share/icons /usr/share/vim \
/usr/share/perl /usr/share/poppler /usr/share/i18n \
/usr/share/cmake /usr/share/cmake-3.22 /usr/share/python-wheels \
/usr/share/emacs /usr/share/emacsen-common /usr/share/java \
/usr/share/iso-codes /usr/share/javascript \
/usr/lib/gcc /usr/lib/git-core /usr/include /var/cache \
/usr/lib/aarch*/libLLVM* /usr/lib/aarch*/perl /usr/lib/aarch*/gconv \
/usr/lib/aarch64-linux-gnu/libasan.so* \
/usr/lib/aarch64-linux-gnu/libtsan.so* \
/usr/lib/aarch64-linux-gnu/liblsan.so* \
/usr/lib/aarch64-linux-gnu/libubsan.so* \
/usr/lib/aarch64-linux-gnu/libhwasan.so* \
/usr/lib/systemd \
/usr/bin/containerd /usr/bin/ctr /usr/bin/runc \
/usr/bin/containerd-shim-runc-v2 \
/usr/bin/cmake /usr/bin/cpack /usr/bin/ctest \
/usr/bin/meson /usr/bin/ninja \
/usr/bin/aarch64-linux-gnu-lto-dump-11 \
/usr/bin/aarch64-linux-gnu-ld* \
/usr/bin/aarch64-linux-gnu-as \
/usr/bin/aarch64-linux-gnu-ar \
/usr/bin/aarch64-linux-gnu-ranlib \
/usr/bin/aarch64-linux-gnu-dwp \
/usr/bin/aarch64-linux-gnu-c++filt \
/usr/bin/aarch64-linux-gnu-nm \
/usr/bin/aarch64-linux-gnu-size \
/usr/bin/aarch64-linux-gnu-cpp* \
/usr/bin/aarch64-linux-gnu-gprof \
/usr/bin/perl /usr/bin/perl5* \
/usr/lib/aarch*/perl-base /usr/lib/aarch*/libperl* \
/opt/robot/.local/lib/python*/site-packages/pygments \
/opt/robot/.cache /root/.cache && \
find /usr -name '*.a' -delete && \
find / -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# --- Final stage: single layer copy ---
FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive
ENV WORKDIR=/opt/robot
ENV ROBOT_THREADS=1
ENV PATH="$PATH:/opt/robot/.local/bin"
ENV ZODOO_SRC=/opt/zodoo
ENV ZODOO_PIPX_HOME=/opt/zodoo_pipx
ENV ZODOO_ENV_DIR=/opt/zodoo_pipx/venvs/zodoo
ENV ZODOO_PYTHON=$ZODOO_ENV_DIR/bin/python3

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

COPY --from=builder / /

WORKDIR /opt/robot
ENTRYPOINT ["/opt/robot/entrypoint.sh"]
