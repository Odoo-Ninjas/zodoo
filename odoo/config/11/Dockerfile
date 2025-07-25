FROM debian:buster
ARG TARGETARCH
ARG ODOO_VERSION
ARG ODOO_INSTALL_LIBPOSTAL
ARG ODOO_CONFIG_DIR
ARG APT_PROXY_IP
ARG APT_OPTIONS
ARG PYPI_SERVER
#ARG CUSTOMS_REQUIREMENTS

#RUN [[ -z "$CUSTOMS_REQUIREMENTS" && exit -1 ]]
ENV LANG=C.UTF-8
RUN sed -i 's|deb.debian.org|archive.debian.org|g' /etc/apt/sources.list && \
    sed -i 's|security.debian.org|archive.debian.org|g' /etc/apt/sources.list && \
    echo 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99no-check-valid-until && \
    apt-get -o Acquire::Retries=3 update
#___SNIPPET_APT_PROXY___

RUN apt-get $APT_OPTIONS update --fix-missing && \
apt-get $APT_OPTIONS install \
        -y \
        --no-install-recommends \
            software-properties-common \
            man \
            cmake \
            ctags \
            build-essential \
            libtool \
            htop \
            ca-certificates \
            curl \
            node-less \
            node-clean-css \
            libpq-dev \
            libjpeg-dev \
            libcurl3-dev \
            libxml2-dev \
            libxslt1-dev \
            libffi-dev \
            tmux \
            libfreetype6-dev \
            libpng-dev \
            libjpeg-dev \
            automake \
            pkg-config \
            libpcre3-dev \
            zlib1g-dev \
            liblzma-dev \
            make \
            ssh \
            mc \
            libxml2-utils \
            libxrender1 \
            libxext6 \
            libfontconfig \
            htop \
            rsync \
            vim \
            psmisc \
            lsof \
            git \
            tig \
            sudo \
            less \
            freetds-dev \
            libsasl2-dev \
            libldap2-dev \
            libssl-dev \
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
            python3-gi \
            python3-click \
            python3-gi-cairo \
            python3-cairo \
            gir1.2-gtk-3.0 \
            libmagickwand-dev \
            libmagic-dev \
            libcups2-dev \
            python3-pip \
            python3-dev \
            python3 \
            locales-all \
            libpoppler-cpp-dev \
            default-jre \
            libreoffice-java-common \
            postgresql-client \
            git \
            libpq-dev \
            autoconf \
            python-dev \
            pkg-config \
            curl \
            python3-venv \
            libcurl4-openssl-dev \
            zlib1g-dev \
            libkrb5-dev


COPY liberation-sans /usr/share/fonts/
# rebuild font cache
RUN fc-cache -f -v

WORKDIR /tmp

RUN apt-get install -y xfonts-75dpi xfonts-base libgeos-dev
RUN if [ "$TARGETARCH" = "amd64" ]; then \
    curl -o wkhtmltox.deb -sSL https://github.com/wkhtmltopdf/wkhtmltopdf/releases/download/0.12.5/wkhtmltox_0.12.5-1.buster_amd64.deb &&  \
    echo 'ea8277df4297afc507c61122f3c349af142f31e5 wkhtmltox.deb' | sha1sum -c - && \
    apt-get install -y --no-install-recommends ./wkhtmltox.deb && \
    rm -rf /var/lib/apt/lists/* wkhtmltox.deb; \
fi
RUN if [ "$TARGETARCH" = "arm64" ]; then \
    curl -o /root/wkhtmltox.deb -sSL  https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6-1/wkhtmltox_0.12.6-1.buster_arm64.deb && \
    apt-get install -y --no-install-recommends /root/wkhtmltox.deb && \
    rm -rf /var/lib/apt/lists/* wkhtmltox.deb;  \
fi

RUN update-alternatives --install /usr/bin/node node /usr/bin/nodejs 10 && \
useradd -ms /bin/bash odoo
RUN \
chown odoo:odoo /home/odoo -R && \
rm -Rf /usr/local/man && mkdir -p /usr/local/man/man1

COPY config/$ODOO_VERSION/odoo_requirements.txt /root/odoo_requirements.txt
COPY config/$ODOO_VERSION/requirements.txt /root/requirements.txt

#p3p3p3p3p3p3p3p3p3p3p3p3p3p3p3p3p3p3p3p3p3p3p3p3p3p3p3p3
# PYTHON 3 and PIP
#p3p3p3p3p3p3p3p3p3p3p3p3p3p3p3p3p3p3p3p3p3p3p3p3p3p3p3p3

#pip3 10.0 is in other directories; hash -r clears the cache of the path
# Optional: speed up installs
ENV PIP_NO_CACHE_DIR=no
# Set custom PyPI index
#___SNIPPET_PYPI_SERVER___
RUN pip3 install wheel
RUN hash -r && \
        pip3 install --upgrade pip && \
        hash -r && \
    pip3 install cython==0.29.35
RUN pip3 install 'setuptools<58.0'
RUN pip3 install psycopg2 pyinotify python-magic wand pycups pudb numpy
RUN pip3 install -r /root/odoo_requirements.txt 
RUN pip3 install -r /root/requirements.txt
#p3p3p3p3p3p3p3p3p3p3p3p3p3p3p3p3p3p3p3p3p3p3p3p3p3p3p3p3

RUN echo "deb http://ftp.de.debian.org/debian buster main " >> /etc/apt/sources.list.d/dmtx && apt-get update && apt-get install -y libdmtx0b
# https://github.com/openvenues/pypostal postal lib for address checking
COPY install_libpostal.sh /root/install_libpostal.sh
RUN if [ "$TARGETARCH" = "amd64" ] && [ "$ODOO_INSTALL_LIBPOSTAL" == "1" ]; then bash /root/install_libpostal.sh; fi


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
pipx install --pip-args="--constraint /opt/constraints.txt" -e $WODOO_SRC && \
echo 'export PATH=$PATH:/usr/local/bin/pipxbin' >> /root/.bashrc
RUN pip3 install $PIP_OPTIONS lxml==4.6.0

RUN apt-get update && apt-get install -y libodbc1 unixodbc-dev unixodbc
RUN pip3 install $PIP_OPTIONS requests-oauth2client faker requests_oauthlib 





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

CMD ["sh", "-c", "/opt/wodoo_pipx/venvs/wodoo/bin/python3 /odoolib/run.py"]
ENTRYPOINT ["/odoolib/entrypoint.sh"]