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

# --------------------------------------------------------------------
# COMPILE PYTHON
# --------------------------------------------------------------------
FROM $BASE_IMAGE AS python_builder
ARG ODOO_PYTHON_VERSION
ADD python/Python-${ODOO_PYTHON_VERSION}.tgz /usr/local/src/python
WORKDIR /usr/local/src/python/Python-${ODOO_PYTHON_VERSION}

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
    freetds-dev \
    ncurses-dev

RUN ./configure --enable-optimizations && make -j4 && make install

RUN #___SNIPPET_APT_INSTALL___ rsync
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

RUN #___SNIPPET_APT_INSTALL___ \
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

#___SNIPPET_PYTHON_INSTALL___

#___SNIPPET_SETUP_PYTHON_VENV___


RUN pip3 install $PIP_OPTIONS wheel && \
pip3 install $PIP_OPTIONS pip -U && \
pip3 install $PIP_OPTIONS setuptools==57.5.0 -U
RUN pip3 install $PIP_OPTIONS "Cython<3"
RUN pip3 install --only-binary :all: pymssql

RUN echo "$ODOO_REQUIREMENTS"  | base64 --decode > /root/pip_requirements.txt

RUN pip3 install --only-binary pymssql $PIP_OPTIONS -r /root/pip_requirements.txt

RUN pip3 install $PIP_OPTIONS \
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

#___SNIPPET_CHECK_SHA___


ENV LANG=C.UTF-8
#___SNIPPET_APT_PROXY___
RUN #___SNIPPET_APT_INSTALL___ \
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

RUN apt-get install -y xfonts-75dpi xfonts-base libgeos-dev
WORKDIR /tmp
RUN if [ "$TARGETARCH" = "amd64" ]; then \
    curl -o /root/wkhtmltox.deb -sSL  https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-2/wkhtmltox_0.12.6.1-2.bullseye_amd64.deb && \
    apt-get install -y --no-install-recommends /root/wkhtmltox.deb && \
    rm -rf /var/lib/apt/lists/* /root/wkhtmltox.deb; \
fi
RUN if [ "$TARGETARCH" = "arm64" ]; then \
    curl -o /root/wkhtmltox.deb -sSL https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-2/wkhtmltox_0.12.6.1-2.bullseye_arm64.deb &&  \
    apt-get install -y --no-install-recommends /root/wkhtmltox.deb && \
    rm -rf /var/lib/apt/lists/* /root/wkhtmltox.deb;  \
fi

#___SNIPPET_NODEJS___

RUN \
chown odoo:odoo /home/odoo -R && \
rm -Rf /usr/local/man && mkdir -p /usr/local/man/man1

# Transfer python
# ENV VIRTUAL_ENV=/opt/venv/env
# ENV PATH="/odoolib:/opt/venv/bin:$PATH"
# RUN rm -Rf /opt/venv
# COPY --from=build_pip /opt/venv /opt/venv


#___SNIPPET_DEB_REQUIREMENTS___

#___SNIPPET_PYTHON_INSTALL___

#___SNIPPET_TRANSFER_VENV___

WORKDIR /opt/odoo


# WODOO
WORKDIR /opt/odoo
RUN python3 -mpip install debugpy docker
RUN mkdir /opt/venv; ln -s /usr/bin /opt/venv/bin
RUN python3 -mpip install pipx
RUN python3 -mpipx ensurepath 
COPY config/$ODOO_VERSION/constraints.txt /opt/constraints.txt
ENV WODOO_SRC=/opt/wodoo
ENV WODOO_PIPX_HOME=/opt/wodoo_pipx
ENV WODOO_ENV_DIR=/opt/wodoo_pipx/venvs/wodoo
ENV WODOO_PYTHON=${WODOO_ENV_DIR}/bin/python3
RUN git clone --depth 1 https://github.com/marcwimmer/wodoo $WODOO_SRC

RUN rm $WODOO_SRC/wodoo/requirements.txt
COPY config/$ODOO_VERSION/wodoo_requirements.txt $WODOO_SRC/wodoo/requirements.txt

RUN \
export PIPX_HOME="${WODOO_PIPX_HOME}" && \
export PIPX_BIN_DIR=/usr/local/bin && \
PIPX_DEFAULT_PYTHON=/opt/venv/bin/python3 \
pipx install --pip-args="$PIP_OPTIONS --constraint /opt/constraints.txt" -e $WODOO_SRC && \
echo 'export PATH=$PATH:/usr/local/bin/pipxbin' >> /root/.bashrc
RUN pip3 install $PIP_OPTIONS lxml==4.6.0




# There is a BUG with M1 and SCRAM authentication
RUN if [ "$TARGETARCH" = "arm64" ]; then \
#___SNIPPET_APT_INSTALL___ \
libpq-dev && \
pip3 install $PIP_OPTIONS psycopg2-binary --no-binary psycopg2-binary --force-reinstall; \
fi
 
RUN #___SNIPPET_APT_INSTALL___ \
coreutils







USER root
RUN echo 'export PATH=$PATH:/usr/local/bin/pipxbin' >> /root/.bashrc


# pudb config
RUN mkdir /home/odoo/.config/pudb -p
RUN chown odoo:odoo /home/odoo/.config -R
ADD pudb.cfg /home/odoo/.config/pudb

RUN touch /helpme

ENV ODOO_USER=odoo
ENV ODOO_DATA_DIR=/opt/files
ENV ODOO_HOME=/opt/odoo
ENV ODOO_CONFIG_TEMPLATE_DIR=/etc/odoo/config.template
ENV ODOO_CONFIG_DIR=/etc/odoo/config
ENV ODOO_SUDO_CMD=1
ENV OUT_DIR=/opt/out_dir
ENV RUN_DIR=/opt/run
ENV INTERCOM_DIR=/intercom
ENV CUSTOMS_DIR=/opt/src
ENV ODOOLIB=/odoolib
ENV PYTHONPATH=/odoolib:/opt/tools
ENV LANG=en_US.UTF-8
ENV LANGUAGE=en_US:en
ENV LC_ALL=en_US.UTF-8
ENV PYTHONBREAKPOINT=0
ENV ODOO_SERVER_TOOLS_MODULES=/opt/odoo_server_tools
ENV ODOO_FRAMEWORK_KEEP_SQL_CONNECTION=1
ENV PATH=/odoolib:/opt/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ENV DOCKER_MACHINE=1

ADD bin/ /odoolib/
ENV ODOO_CONFIG_DIR=${ODOO_CONFIG_DIR}
ADD config/${ODOO_VERSION}/config ${ODOO_CONFIG_DIR}.template
