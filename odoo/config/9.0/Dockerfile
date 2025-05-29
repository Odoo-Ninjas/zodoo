FROM ubuntu:22.04
ARG ODOO_VERSION
ENV DEBIAN_FRONTEND=noninteractive

RUN apt update --fix-missing && \
apt-get install \
	-y \
	--no-install-recommends \
			software-properties-common \
			man \
            cmake \
            universal-ctags \
			build-essential \
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
            python3-pip \
            python3-setuptools \
            python3-dev \
            pdftk \
            libmagic-dev

RUN \
locale-gen en_US.UTF-8 && \
update-locale && \
echo 'LC_ALL=en_US.UTF-8' >> /etc/environment && \
echo 'LANG=en_US.UTF-8' >> /etc/environment && \
echo 'LANGUAGE=en_US.UTF-8' >> /etc/environment 

COPY liberation-sans /usr/share/fonts/
# rebuild font cache
RUN fc-cache -f -v

# Install nodejs and npm
RUN apt install -y nodejs yarn

# libreoffice
#RUN apt-get update && \
#apt install -q -y libreoffice libreoffice-writer ure libreoffice-java-common libreoffice-core libreoffice-common openjdk-8-jre fonts-opensymbol hyphen-fr hyphen-de hyphen-en-us hyphen-it hyphen-ru fonts-dejavu fonts-dejavu-core fonts-dejavu-extra fonts-droid-fallback fonts-dustin fonts-f500 fonts-fanwood fonts-freefont-ttf fonts-liberation fonts-lmodern fonts-lyx fonts-sil-gentium fonts-texgyre fonts-tlwg-purisa && \
#apt -y -q remove libreoffice-gnome

WORKDIR /tmp

RUN curl -o wkhtmltox.tar.xz -SL https://github.com/wkhtmltopdf/wkhtmltopdf/releases/download/0.12.4/wkhtmltox-0.12.4_linux-generic-amd64.tar.xz \
        && echo '3f923f425d345940089e44c1466f6408b9619562 wkhtmltox.tar.xz' | sha1sum -c - \
        && tar xvf wkhtmltox.tar.xz \
        && cp wkhtmltox/lib/* /usr/local/lib/ \
        && cp wkhtmltox/bin/* /usr/local/bin/ \
        && cp -r wkhtmltox/share/man/man1 /usr/local/share/man/


RUN update-alternatives --install /usr/bin/node node /usr/bin/nodejs 10 && \
useradd -ms /bin/bash odoo
RUN \
chown odoo:odoo /home/odoo -R && \
rm -Rf /usr/local/man && mkdir -p /usr/local/man/man1
RUN apt install -y libpython2-dev python2 python2-dev
RUN apt update && apt install -y python-setuptools
RUN pip install --no-cache-dir lxml
RUN ls -lhtra /usr/bin
RUN curl https://bootstrap.pypa.io/pip/2.7/get-pip.py --output get-pip.py
RUN apt update && apt install -y python3 python3-pip
RUN cd /usr/bin && ln -s python2.7 python
RUN python2.7 get-pip.py

RUN pip install --no-cache-dir pip --upgrade
RUN pip install --no-cache-dir cython==0.29.36

RUN \
	pip install --no-cache-dir requests[security] && \
	pip install --no-cache-dir glob2
RUN pip install --no-cache-dir pip --upgrade
RUN pip install --no-cache-dir lxml psycopg2-binary click pudb psutil

COPY config/$ODOO_VERSION/requirements.txt /root/requirements.txt
RUN pip install --no-cache-dir pathlib2
RUN pip install --no-cache-dir -r /root/requirements.txt --no-build-isolation
RUN pip install --no-cache-dir python-magic==0.4.25

# python2 binary error on ubuntu 18.04
# https://github.com/psycopg/psycopg2-wheels/issues/2
RUN mv /bin/sh /bin/sh.bak; ln -s /bin/bash /bin/sh
RUN pip install --no-cache-dir psycopg2
RUN rm /bin/sh; mv /bin/sh.bak /bin/sh


RUN apt update
RUN apt install -y python3-pip
COPY config/${ODOO_VERSION}/pip3 /usr/local/bin/pip3
RUN chmod a+x /usr/local/bin/pip3
RUN pip3 install --no-cache-dir humanize retrying click pyyaml requests passlib arrow inquirer tabulate psutil iscompatible lxml psycopg2 pudb docker gitpython


WORKDIR /opt

ENV PYTHONIOENCODING=utf8

RUN pip install --no-cache-dir pudb ipython docker gitpython
RUN echo "\nimport sys; sys.setdefaultencoding('utf-8')" >> /etc/python2.7/sitecustomize.py

RUN pip install --no-cache-dir gevent==1.2.2
RUN pip install --no-cache-dir psycopg2==2.8.6 pathlib==1.0.1

RUN \
apt update && \
apt install -y python3.10-venv && \
python3.10 -mpip install pipx && \
python3.10 -mpipx ensurepath

RUN \
PIPX_DEFAULT_PYTHON=python3.10 \
PIPX_HOME=/opt/wodoo_env \
PIPX_BIN_DIR=/usr/local/bin/pipxbin \
python3.10 -mpipx install wodoo && \
echo 'export PATH=$PATH:/usr/local/bin/pipxbin' >> /root/.bashrc