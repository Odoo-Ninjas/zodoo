# use buster for latest postgres client
ARG TARGETARCH
ARG BASE_IMAGE=debian:bullseye
ARG ODOO_VERSION
ARG ODOO_REQUIREMENTS
ARG ODOO_DEB_REQUIREMENTS
ARG ODOO_FRAMEWORK_REQUIREMENTS
ARG ODOO_PYTHON_VERSION
ARG ODOO_INSTALL_LIBPOSTAL
ARG CUSTOMS_SHA
ARG ODOO_CONFIG_DIR
ARG APT_PROXY_IP
ARG APT_OPTIONS
ARG PYPI_SERVER
ARG DOCKER_GID

# --------------------------------------------------------------------
# COMPILE PYTHON
# --------------------------------------------------------------------
FROM $BASE_IMAGE AS python_builder
ARG ODOO_PYTHON_VERSION
ADD python/Python-${ODOO_PYTHON_VERSION}.tgz /usr/local/src/python
WORKDIR /usr/local/src/python/Python-${ODOO_PYTHON_VERSION}

#___SNIPPET_APT_PROXY___
RUN apt-get $APT_OPTIONS update && apt-get $APT_OPTIONS install -y \
    software-properties-common \
    cmake \
    exuberant-ctags \
    build-essential \
    zlib1g-dev \
    make \
    libssl-dev \
    libffi-dev \
    libsqlite3-dev  \
    libjpeg-dev \
    libcurl3-dev \
    libxml2-dev \
    libxslt1-dev \
    libfreetype6-dev \
    libpng-dev \
    libpcre3-dev \
    liblzma-dev \
    freetds-dev \
    ncurses-dev

RUN ./configure --enable-optimizations && make -j4 && make install

RUN apt-get $APT_OPTIONS install -y rsync
RUN rsync /usr/local/src/python/Python-${ODOO_PYTHON_VERSION}/ /python -ar



# --------------------------------------------------------------------
# PYTHON PIP PACKAGES
# --------------------------------------------------------------------
FROM $BASE_IMAGE AS build_pip
ARG ODOO_DEB_REQUIREMENTS
ARG ODOO_REQUIREMENTS
ARG ODOO_FRAMEWORK_REQUIREMENTS
ARG APT_PROXY_IP
ARG APT_OPTIONS
ARG PYPI_SERVER

ENV VIRTUAL_ENV=/opt/venv/env
ENV PATH="/opt/venv/bin:$PATH"

RUN apt-get $APT_OPTIONS update && apt-get $APT_OPTIONS install -y \
    build-essential \
    libxml2-dev \
    libxslt1-dev \
    libcups2-dev \
    libpq-dev \
    libsasl2-dev \
    libpython3-dev \
    libldap2-dev \
    libssl-dev \
    libpoppler-cpp-dev \
    pkg-config \
    libfreetype6-dev \
    freetds-dev \
    libkrb5-dev \
    git

COPY --from=python_builder /python /opt/python
WORKDIR /opt/python
RUN make install
RUN python3 -m venv --copies /opt/venv


RUN pip3 install --no-cache-dir wheel && \
pip3 install --no-cache-dir pip -U && \
pip3 install --no-cache-dir setuptools==57.5.0 -U && \
pip3 install --no-cache-dir cython==0.29.35

RUN echo "$ODOO_REQUIREMENTS"  | base64 --decode > /root/pip_requirements.txt

# Optional: speed up installs
ENV PIP_NO_CACHE_DIR=no
# Set custom PyPI index
RUN pip3 config set global.index-url $PYPI_SERVER
RUN pip3 install --no-cache-dir --no-build-isolation -r /root/pip_requirements.txt

RUN pip3 install \
--no-cache-dir \
pudb ipython \
debugpy psycopg2-binary \
pyinotify python-magic wand \
pycups pudb ipython


COPY patches/python_3.8.email.patch /usr/local/src
RUN bash /usr/local/src/python_3.8.email.patch

# Openupgradelib
RUN apt-get install -y git
RUN git clone https://github.com/OCA/openupgradelib /opt/openupgradelib
WORKDIR /opt/openupgradelib
RUN pip3 install --no-cache-dir /opt/openupgradelib

# --------------------------------------------------------------------
# ODOO
# --------------------------------------------------------------------
FROM $BASE_IMAGE
ARG TARGETARCH
ARG ODOO_VERSION
ARG ODOO_REQUIREMENTS
ARG ODOO_DEB_REQUIREMENTS
ARG ODOO_INSTALL_LIBPOSTAL
ARG CUSTOMS_SHA

COPY bin/check_sha.sh /usr/local/bin
RUN /bin/bash /usr/local/bin/check_sha.sh "$CUSTOMS_SHA"


ENV LANG=C.UTF-8
RUN apt-get $APT_OPTIONS update
RUN apt-get $APT_OPTIONS install \
	-y \
	--no-install-recommends \
			man \
            exuberant-ctags \
            libtool \
            htop \
            ca-certificates \
            curl \
            node-less \
			node-clean-css \
            ssh \
            libxml2-utils \
            libxrender1 \
            libxext6 \
            libfontconfig \
            rsync \
            vim \
            psmisc \
            git \
            sudo \
            less \
            freetds-dev \
            wget \
            cifs-utils \
            imagemagick \
            cups \
            libreoffice \
            libcairo2 libpango1.0-0 libgdk-pixbuf2.0-0 libffi-dev shared-mime-info \
            locales \
			libmagickwand-dev \
            ffmpeg \
            zip \
            gpg-agent \
            pdftk \
            gir1.2-gtk-3.0 \
            libmagickwand-dev \
            libmagic-dev \
            libcups2-dev \
            python3-pip \
            python3-dev \
            python3 \
            locales-all \
            postgresql-client \
            sassc \
            libsqlite3-dev \
            autoconf \
            pkg-config \
            curl \
            time \
            libpoppler-cpp-dev \
            libncurses5 \
            libncurses5-dev \
            libncursesw5 \
            libgeos-dev \
            xfonts-75dpi \
            xfonts-base

COPY liberation-sans /usr/share/fonts/
# rebuild font cache
RUN fc-cache -f -v

#___SNIPPET_WKHTML2PDF___

#___SNIPPET_NODEJS___

RUN \
chown odoo:odoo /home/odoo -R && \
rm -Rf /usr/local/man && mkdir -p /usr/local/man/man1

# Transfer python
ENV VIRTUAL_ENV=/opt/venv/env
ENV PATH="/odoolib:/opt/venv/bin:$PATH"
RUN rm -Rf /opt/venv
COPY --from=build_pip /opt/python /opt/python
COPY --from=build_pip /opt/venv /opt/venv
WORKDIR /opt/python
RUN make install
RUN rm /usr/local/bin/python3 /usr/bin/python3

RUN echo "$ODOO_DEB_REQUIREMENTS"  | base64 --decode > /root/deb_requirements.txt
RUN apt-get $APT_OPTIONS update && xargs apt-get $APT_OPTIONS install -y < /root/deb_requirements.txt

WORKDIR /opt/odoo


# There is a BUG with M1 and SCRAM authentication
RUN if [ "$TARGETARCH" = "arm64" ]; then \
apt-get $APT_OPTIONS update && \
apt-get $APT_OPTIONS install -y libpq-dev && \
pip3 install --no-cache-dir psycopg2-binary --no-binary psycopg2-binary --force-reinstall; \
fi

RUN apt $APT_OPTIONS install -y coreutils