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

# --------------------------------------------------------------------
# COMPILE PYTHON
# --------------------------------------------------------------------
FROM $BASE_IMAGE AS python_builder
ARG ODOO_PYTHON_VERSION
COPY python/Python-${ODOO_PYTHON_VERSION}.tgz /usr/local/src/python
WORKDIR /usr/local/src/python/Python-${ODOO_PYTHON_VERSION}

RUN apt-get update && \
apt-get install -y \
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

RUN apt-get install -y rsync
RUN rsync /usr/local/src/python/Python-${ODOO_PYTHON_VERSION}/ /python -ar



# --------------------------------------------------------------------
# PYTHON PIP PACKAGES
# --------------------------------------------------------------------
FROM $BASE_IMAGE AS build_pip
ARG ODOO_DEB_REQUIREMENTS
ARG ODOO_REQUIREMENTS
ARG ODOO_FRAMEWORK_REQUIREMENTS

ENV VIRTUAL_ENV=/opt/venv/env
ENV PATH="/opt/venv/bin:$PATH"

RUN apt-get update && apt-get install -y \
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
    freetds-dev

#___SNIPPET_PYTHON_INSTALL___

RUN pip3 install $PIP_OPTIONS wheel && \
pip3 install $PIP_OPTIONS pip -U && \
pip3 install $PIP_OPTIONS setuptools -U

RUN echo "$ODOO_REQUIREMENTS"  | base64 --decode > /root/pip_requirements.txt
RUN pip3 install $PIP_OPTIONS -r /root/pip_requirements.txt

RUN echo "$ODOO_FRAMEWORK_REQUIREMENTS"  | base64 --decode > /root/framework_requirements.txt
RUN pip3 install $PIP_OPTIONS -r /root/framework_requirements.txt

RUN pip3 install $PIP_OPTIONS  \
pudb ipython marabunta \
wodoo debugpy psycopg2-binary \
pyinotify python-magic wand \
pycups pudb ipython

COPY patches/python_3.8.email.patch /usr/local/src
RUN bash /usr/local/src/python_3.8.email.patch

# Openupgradelib
RUN apt-get install -y git
RUN git clone https://github.com/OCA/openupgradelib /opt/openupgradelib
WORKDIR /opt/openupgradelib
RUN pip3 install $PIP_OPTIONS /opt/openupgradelib

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

#___SNIPPET_APT_PROXY___


ENV LANG=C.UTF-8
RUN apt-get update
RUN apt-get install \
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
RUN apt-get update && xargs apt-get install -y < /root/deb_requirements.txt

# RUN python3 -mpip install cython
RUN apt-get update; apt-get install -y \
libpq-dev \
libxml2-dev libxslt1-dev \
libsasl2-dev python-dev libldap2-dev libssl-dev \
g++
RUN \
python3 -mpip install psycopg2-binary==2.8 && \
python3 -mpip install gevent && \
python3 -mpip install greenlet
COPY config/12.0/requirements.txt requirements.txt
RUN python3 -mpip install $PIP_OPTIONS -r requirements.txt
RUN python3 -mpip install $PIP_OPTIONS babel ics pdf2image zxcvbn reportlab==3.6.12 odoorpc
RUN pip3 install $PIP_OPTIONS lxml[html_clean]==4.8.0

# install wodoo
RUN \
python3 -mpip install pipx && \
python3 -mpipx ensurepath && \
mkdir /usr/local/bin/pipxbin && \

PIPX_DEFAULT_PYTHON=/opt/venv/bin/python3 \
PIPX_HOME=/opt/wodoo_env \
PIPX_BIN_DIR=/usr/local/bin/pipxbin \
pipx install wodoo && \
echo 'export PATH=$PATH:/usr/local/bin/pipxbin' >> /root/.bashrc

RUN pip install $PIP_OPTIONS pillow==6.1.0
RUN pip install $PIP_OPTIONS cachetools==2.0.1
RUN pip install $PIP_OPTIONS dicttoxml==1.7.4
RUN pip install $PIP_OPTIONS openpyxl==2.6.4
RUN pip install $PIP_OPTIONS xmltodict==0.12.0
RUN pip install $PIP_OPTIONS zeep==3.4.0
RUN pip install $PIP_OPTIONS sentry-sdk==0.19.5

WORKDIR /opt/odoo

