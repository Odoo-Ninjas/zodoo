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

# --------------------------------------------------------------------
# COMPILE LIBPOSTAL
# --------------------------------------------------------------------
FROM $BASE_IMAGE AS libpostal_builder
ARG TARGETARCH
ARG ODOO_INSTALL_LIBPOSTAL
ADD install_libpostal.sh /root/install_libpostal.sh
RUN if [ "$TARGETARCH" = "amd64" ]; then bash /root/install_libpostal.sh; fi

# --------------------------------------------------------------------
# COMPILE PYTHON
# --------------------------------------------------------------------
FROM $BASE_IMAGE AS python_builder
ARG ODOO_PYTHON_VERSION
ARG APT_PROXY_IP
ARG PYPI_SERVER
ARG APT_OPTIONS
COPY python/Python-${ODOO_PYTHON_VERSION}.tgz /usr/local/src/python
WORKDIR /usr/local/src
RUN tar xfz /usr/local/src/python
WORKDIR /usr/local/src/Python-${ODOO_PYTHON_VERSION}

RUN echo "Acquire::http::Proxy \"http://${APT_PROXY_IP}:3142\";" > /etc/apt/apt.conf.d/01proxy

RUN apt update && \
apt -o Acquire::Retries=5 \
    install -y \
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

RUN echo "Acquire::http::Proxy \"http://${APT_PROXY_IP}:3142\";" > /etc/apt/apt.conf.d/01proxy
RUN apt update && \
    apt -o Acquire::Retries=5 \
    install -y \
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
RUN pip3 install wheel && \
pip3 install pip -U && \
pip3 install setuptools -U

RUN echo "$ODOO_DEB_REQUIREMENTS"  | base64 --decode > /root/deb_requirements.txt
RUN xargs apt -o Acquire::Retries=5 install -y < /root/deb_requirements.txt

RUN echo "$ODOO_REQUIREMENTS"  | base64 --decode > /root/pip_requirements.txt
RUN pip3 install -r /root/pip_requirements.txt --force --force-reinstall --ignore-installed

RUN echo "$ODOO_FRAMEWORK_REQUIREMENTS"  | base64 --decode > /root/framework_requirements.txt
RUN pip3 install -r /root/framework_requirements.txt

RUN pip3 install pudb ipython debugpy

# Openupgradelib
RUN apt $APT_OPTIONS install -y git
RUN git clone https://github.com/OCA/openupgradelib /opt/openupgradelib
WORKDIR /opt/openupgradelib
RUN pip3 install /opt/openupgradelib



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
ARG PYPI_SERVER
ARG APT_OPTIONS

MAINTAINER marc@itewimmer.de

ADD bin/check_sha.sh /usr/local/bin
RUN /bin/bash /usr/local/bin/check_sha.sh "$CUSTOMS_SHA"


ENV LANG C.UTF-8
RUN echo "Acquire::http::Proxy \"http://${APT_PROXY_IP}:3142\";" > /etc/apt/apt.conf.d/01proxy

RUN apt update && \
    apt $APT_OPTIONS install \
	-y \
	--no-install-recommends \
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

ADD liberation-sans /usr/share/fonts/
# rebuild font cache
RUN fc-cache -f -v

WORKDIR /tmp

RUN if [ "$TARGETARCH" = "amd64" ]; then \
    curl -o /root/wkhtmltox.deb -sSL  https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-2/wkhtmltox_0.12.6.1-2.jammy_amd64.deb && \
    apt update && apt $APT_OPTIONS install -y --no-install-recommends /root/wkhtmltox.deb && \
    rm -rf /var/lib/apt/lists/* /root/wkhtmltox.deb; \
fi
RUN if [ "$TARGETARCH" = "arm64" ]; then \
    curl -o /root/wkhtmltox.deb -sSL https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-2/wkhtmltox_0.12.6.1-2.jammy_arm64.deb &&  \
    apt update && apt $APT_OPTIONS install -y --no-install-recommends /root/wkhtmltox.deb && \
    rm -rf /var/lib/apt/lists/* /root/wkhtmltox.deb;  \
fi

# Node-JS
RUN update-alternatives --install /usr/bin/node node /usr/bin/nodejs 10 && \
useradd -ms /bin/bash odoo
RUN \
chown odoo:odoo /home/odoo -R && \
rm -Rf /usr/local/man && mkdir -p /usr/local/man/man1

# install docker client
ENV DEBIAN_FRONTEND=noninteractive
RUN \
if [ "$INSTALL_DOCKER_CLIENTS" = "1" ]; then \
    groupadd -g $DOCKER_GROUP_ID docker && \
    usermod -aG docker odoo && \
    apt update && \
    apt $APT_OPTIONS install -y ca-certificates curl gnupg lsb-release software-properties-common && \
    apt update && \
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/debian \
    $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null && \
    apt update && \
    apt $APT_OPTIONS install -y docker-ce-cli && \
    echo 'done'; \
fi

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
#ADD install_libpostal.sh /root/install_libpostal.sh
#ADD install_libpostal.sh /root/install_libpostal.sh
#RUN if [ "$TARGETARCH" = "amd64" ] && [ "$ODOO_INSTALL_LIBPOSTAL" == "1" ]; then bash /root/install_libpostal.sh; fi
#RUN if [ "$TARGETARCH" = "amd64" ]; then bash /root/install_libpostal.sh; fi


RUN echo "$ODOO_DEB_REQUIREMENTS"  | base64 --decode > /root/deb_requirements.txt
RUN apt update && xargs apt $APT_OPTIONS install -y < /root/deb_requirements.txt

WORKDIR /opt/odoo

# There is a BUG with M1 and SCRAM authentication

RUN if [ "$TARGETARCH" = "arm64" ]; then \
apt update && \
apt $APT_OPTIONS install -y libpq-dev build-essential && \
/opt/venv/bin/python3 -mpip install psycopg2-binary --no-binary psycopg2-binary --force-reinstall; \
fi
