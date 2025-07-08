ARG TARGETARCH
ARG BASE_IMAGE=ubuntu:22.04
ARG ODOO_VERSION
ARG ODOO_REQUIREMENTS
ARG ODOO_DEB_REQUIREMENTS
ARG ODOO_INSTALL_LIBPOSTAL
ARG ODOO_PYTHON_VERSION
ARG ODOO_CONFIG_DIR
ARG CUSTOMS_SHA
ARG APT_PROXY_IP
ARG PYPI_SERVER
ARG APT_OPTIONS
ARG DOCKER_GID

# --------------------------------------------------------------------
# COMPILE PYTHON
# --------------------------------------------------------------------
FROM $BASE_IMAGE AS python_builder
ARG ODOO_PYTHON_VERSION
ARG APT_PROXY_IP
ARG APT_OPTIONS
ARG PYPI_SERVER
COPY python/Python-${ODOO_PYTHON_VERSION}.tgz /usr/local/src/python
WORKDIR /usr/local/src
RUN tar xfz /usr/local/src/python
WORKDIR /usr/local/src/Python-${ODOO_PYTHON_VERSION}

#___SNIPPET_APT_PROXY___
RUN #___SNIPPET_APT_INSTALL___ \
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
    freetds-dev  \
    libbz2-dev \
    ncurses-dev \
    rsync

#___SNIPPET_BUILD_PYTHON___


# --------------------------------------------------------------------
# PYTHON PIP PACKAGES
# --------------------------------------------------------------------
FROM $BASE_IMAGE AS build_pip
ARG ODOO_DEB_REQUIREMENTS
ARG ODOO_REQUIREMENTS
ARG ODOO_FRAMEWORK_REQUIREMENTS
ARG APT_PROXY_IP
ARG PYPI_SERVER
ARG APT_OPTIONS

ENV VIRTUAL_ENV=/opt/venv/env
ENV PATH="/opt/venv/bin:$PATH"

#___SNIPPET_APT_PROXY___
RUN #___SNIPPET_APT_INSTALL___ \
    build-essential \
    libxml2-dev \
    libxslt1-dev \
    libcups2-dev \
    libpq-dev \
    libsasl2-dev \
    python-dev-is-python3 \
    libldap2-dev \
    libssl-dev \
    libpoppler-cpp-dev \
    pkg-config \
    libfreetype6-dev \
    freetds-dev \
    libffi-dev \
    libkrb5-dev \
    cmake \
    git

#___SNIPPET_DEB_REQUIREMENTS___

#___SNIPPET_PYTHON_INSTALL___

#___SNIPPET_SETUP_PYTHON_VENV___

#___SNIPPET_PYPI_SERVER___

RUN pip3 install $PIP_OPTIONS wheel && \
pip3 install $PIP_OPTIONS pip -U && \
pip3 install $PIP_OPTIONS setuptools -U


RUN echo "$ODOO_REQUIREMENTS"  | base64 --decode > /root/pip_requirements.txt
RUN pip install "Cython<3"
RUN pip3 install $PIP_OPTIONS -r /root/pip_requirements.txt --force --force-reinstall --ignore-installed

RUN echo "$ODOO_FRAMEWORK_REQUIREMENTS"  | base64 --decode > /root/framework_requirements.txt
RUN pip3 install $PIP_OPTIONS -r /root/framework_requirements.txt

RUN pip3 install $PIP_OPTIONS pudb ipython debugpy

#___SNIPPET_OPENUPGRADELIB___

# --------------------------------------------------------------------
# ODOO
# --------------------------------------------------------------------
FROM $BASE_IMAGE
ARG TARGETARCH
ARG ODOO_VERSION
ARG ODOO_REQUIREMENTS
ARG ODOO_DEB_REQUIREMENTS
ARG ODOO_PYTHON_VERSION
ARG DOCKER_GROUP_ID
ARG INSTALL_DOCKER_CLIENTS
ARG CUSTOMS_SHA
ARG APT_PROXY_IP
ARG PYPI_SERVER
ARG APT_OPTIONS
ARG DOCKER_GID

#___SNIPPET_CHECK_SHA___


ENV LANG=C.UTF-8
ENV PIP_NO_CACHE_DIR=no

#___SNIPPET_APT_PROXY___
RUN #___SNIPPET_APT_INSTALL___ \
            man \
            htop \
            ca-certificates \
            curl \
            node-less \
            node-clean-css \
            tmux \
            libfreetype6-dev \
            libpng-dev \
            libjpeg-dev \
            automake \
            pkg-config \
            libpcre3-dev \
            liblzma-dev \
            make \
            ssh \
            mc \
            libfontconfig \
            rsync \
            psmisc \
            lsof \
            git \
            sudo \
            less \
            freetds-dev \
            wget \
            cifs-utils \
            imagemagick \
            cups \
            locales \
            libmagickwand-dev \
            ffmpeg \
            zip \
            gpg-agent \
            pdftk \
            python3-gi \
            python3-click \
            python3-gi-cairo \
            python3-cairo \
            gir1.2-gtk-3.0 \
            libmagickwand-dev \
            libmagic-dev \
            libcups2-dev \
            locales-all \
            libpoppler-cpp-dev \
            locales \
            postgresql-client \
            sassc \
            time \
            xfonts-75dpi \
            xfonts-base \
            libgeos-dev

COPY liberation-sans /usr/share/fonts/
# rebuild font cache
RUN fc-cache -f -v
RUN locale-gen en_US.UTF-8 && dpkg-reconfigure locales

#___SNIPPET_WKHTML2PDF___

#___SNIPPET_NODEJS___

RUN \
chown odoo:odoo /home/odoo -R && \
rm -Rf /usr/local/man && mkdir -p /usr/local/man/man1

#___SNIPPET_PYTHON_INSTALL___

#___SNIPPET_TRANSFER_VENV___

#___SNIPPET_DEB_REQUIREMENTS___

WORKDIR /usr/local/bin
RUN rm python3 && ln -s /opt/venv/bin/python3

WORKDIR /opt/odoo

#___SNIPPET_COPY_OPENUPGRADE_LIB___

#___SNIPPET_M1_BUG___