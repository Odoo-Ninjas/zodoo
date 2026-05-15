FROM ubuntu:22.04 AS builder
ARG POSTGRES_VERSION
ENV DEBIAN_FRONTEND=noninteractive
ENV POSTGRES_VERSION=$POSTGRES_VERSION
ENV PIP_NO_CACHE_DIR=no

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

#___SNIPPET_APT_PROXY___
#___SNIPPET_UPDATE_CA_CERTIFICATES___
#___SNIPPET_UBUNTU_ARCHIVES_HTTPS___

RUN #___SNIPPET_APT_INSTALL___ \
python3-pip python3 python3.11 curl rsync locales pv \
pigz telnet libpq-dev wget lsb-release \
libxml2-dev libxslt-dev pipx gosu git sudo \
ca-certificates curl gnupg lsb-release \
unzip libpq-dev python3.11-dev

# install docker
#___SNIPPET_DOCKER___

# install postgres
#___SNIPPET_POSTGRES___

WORKDIR /usr/local/bin

RUN #___SNIPPET_APT_INSTALL___ \
python3-lxml

WORKDIR /root
COPY requirements.txt requirements.txt

RUN #___SNIPPET_APT_INSTALL___ \
build-essential gcc python3-dev tmux && \
python3 -mpip install $(cat /etc/pip_options) -r requirements.txt

#___SNIPPET_PYTHON311___
#___SNIPPET_ZODOO___

COPY entrypoint.sh /entrypoint.sh
RUN chmod a+x /entrypoint.sh

COPY bin/ /usr/local/bin/
RUN chmod a+x /usr/local/bin/*.py /usr/local/bin/*.sh

RUN #___SNIPPET_APT_INSTALL___ \
ncdu

# cleanup in builder so the final COPY --from=builder gets clean files
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
/usr/lib/systemd /usr/libexec/docker/docker-init \
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
/root/.cache && \
find /usr -name '*.a' -delete && \
find / -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# --- Final stage: single layer copy ---
FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive
ARG POSTGRES_VERSION
ENV POSTGRES_VERSION=$POSTGRES_VERSION
ENV PIP_NO_CACHE_DIR=no
ENV ZODOO_SRC=/opt/zodoo
ENV ZODOO_PIPX_HOME=/opt/zodoo_pipx
ENV ZODOO_ENV_DIR=/opt/zodoo_pipx/venvs/zodoo
ENV ZODOO_PYTHON=$ZODOO_ENV_DIR/bin/python3

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Copy entire filesystem from builder (cleaned)
COPY --from=builder / /

ENTRYPOINT ["/entrypoint.sh"]
