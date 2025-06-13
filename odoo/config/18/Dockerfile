ARG TARGETARCH
ARG BASE_IMAGE=ubuntu:22.04
ARG ODOO_VERSION
ARG ODOO_REQUIREMENTS
ARG ODOO_DEB_REQUIREMENTS
ARG ODOO_INSTALL_LIBPOSTAL
ARG ODOO_PYTHON_VERSION
ARG ODOO_CONFIG_DIR
ARG CUSTOMS_SHA
ARG APT_OPTIONS
ARG APT_PROXY_IP
ARG PYPI_SERVER
ARG DOCKER_GID

# --------------------------------------------------------------------
# COMPILE LIBPOSTAL
# --------------------------------------------------------------------
FROM $BASE_IMAGE AS libpostal_builder
ARG TARGETARCH
ARG ODOO_INSTALL_LIBPOSTAL
COPY install_libpostal.sh /root/install_libpostal.sh
RUN if [ "$TARGETARCH" = "amd64" ]; then bash /root/install_libpostal.sh; fi

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

RUN ./configure --enable-optimizations && make -j4 && make install
RUN rsync /usr/local/src/Python-${ODOO_PYTHON_VERSION}/ /python -ar



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
#___SNIPPET_APT_INSTALL___ \ 
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
    freetds-dev  \
    libffi-dev \
    libkrb5-dev \
    cmake \
    git

# install python from compiled binaries
COPY --from=python_builder /python /opt/python
WORKDIR /opt/python
RUN make install
RUN python3 -m venv --copies /opt/venv

# Optional: speed up installs
ENV PIP_NO_CACHE_DIR=no
# Set custom PyPI index
RUN pip3 config set global.index-url $PYPI_SERVER

RUN pip3 install --no-cache-dir wheel && \
pip3 install --no-cache-dir pip -U && \
pip3 install --no-cache-dir setuptools -U

RUN echo "$ODOO_DEB_REQUIREMENTS"  | base64 --decode > /root/deb_requirements.txt
RUN xargs apt-get $APT_OPTIONS install -y < /root/deb_requirements.txt

RUN echo "$ODOO_REQUIREMENTS"  | base64 --decode > /root/pip_requirements.txt
RUN pip3 install --no-cache-dir  -r /root/pip_requirements.txt --force --force-reinstall --ignore-installed

RUN echo "$ODOO_FRAMEWORK_REQUIREMENTS"  | base64 --decode > /root/framework_requirements.txt
RUN pip3 install --no-cache-dir  -r /root/framework_requirements.txt

RUN pip3 install --no-cache-dir pudb ipython debugpy

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
ARG ODOO_INSTALL_LIBPOSTAL
ARG CUSTOMS_SHA
ARG APT_PROXY_IP
ARG APT_OPTIONS
ARG PYPI_SERVER
ARG DOCKER_GID

COPY bin/check_sha.sh /usr/local/bin
RUN /bin/bash /usr/local/bin/check_sha.sh "$CUSTOMS_SHA"

# Optional: speed up installs
ENV PIP_NO_CACHE_DIR=no
# Set custom PyPI index

ENV LANG=C.UTF-8

#___SNIPPET_APT_PROXY___
#___SNIPPET_APT_INSTALL___ \
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
            libreoffice \
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
            postgresql-client \
            sassc \
            time \
            xfonts-75dpi \
            xfonts-base \
            libgeos-dev

COPY liberation-sans /usr/share/fonts/
# rebuild font cache
RUN fc-cache -f -v


#___SNIPPET_WKHTML2PDF___

#___SNIPPET_NODEJS___

# Transfer python
ENV VIRTUAL_ENV=/opt/venv/env
ENV PATH="/odoolib:/opt/venv/bin:$PATH"
RUN rm -Rf /opt/venv
COPY --from=build_pip /opt/python /opt/python
COPY --from=build_pip /opt/venv /opt/venv
WORKDIR /opt/python
RUN make install
#RUN rm /usr/local/bin/python3 /usr/bin/python3


# Transfer lib postal (TODO)
#COPY install_libpostal.sh /root/install_libpostal.sh
#COPY install_libpostal.sh /root/install_libpostal.sh
#RUN if [ "$TARGETARCH" = "amd64" ] && [ "$ODOO_INSTALL_LIBPOSTAL" == "1" ]; then bash /root/install_libpostal.sh; fi
#RUN if [ "$TARGETARCH" = "amd64" ]; then bash /root/install_libpostal.sh; fi


RUN echo "$ODOO_DEB_REQUIREMENTS"  | base64 --decode > /root/deb_requirements.txt
RUN apt-get $APT_OPTIONS update && xargs apt-get $APT_OPTIONS install -y < /root/deb_requirements.txt

WORKDIR /opt/odoo

#___SNIPPET_COPY_OPENUPGRADE_LIB___
# There is a BUG with M1 and SCRAM authentication

RUN if [ "$TARGETARCH" = "arm64" ]; then \
apt-get $APT_OPTIONS update && \
apt-get $APT_OPTIONS install -y --no-install-recommends libpq-dev build-essential && \
/opt/venv/bin/python3 -mpip install psycopg2-binary --no-binary psycopg2-binary --force-reinstall; \
fi
