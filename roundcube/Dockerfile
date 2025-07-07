# TODO: COPY apt mirror
FROM    ubuntu:20.04
ENV     DEBIAN_FRONTEND=noninteractive
ENV     TERM=xterm
ENV     ROUNDCUBE_VERSION=1.6.6
ENV     MAIL_SERVER=mail
ARG     APT_PROXY_IP
ARG     APT_OPTIONS
ARG     PYPI_SERVER

RUN apt update

WORKDIR /root
RUN mkdir -p /rc
RUN apt upgrade -y && apt $APT_OPTIONS install -y php-net-ldap2 php-net-ldap3 php-imagick php7.4-common php7.4-gd php7.4-imap php7.4-json php7.4-curl php7.4-zip php7.4-xml php7.4-mbstring php7.4-bz2 php7.4-intl php7.4-gmp php7.4-fpm php7.4-sqlite3
RUN apt $APT_OPTIONS install -y nginx wget composer

#___SNIPPET_PYPI_SERVER___

RUN \
apt $APT_OPTIONS install -y python3-pip && \
pip3 install --no-cache-dir pip --upgrade && \
pip3 install --no-cache-dir wheel && \
pip3 install --no-cache-dir pathlib
RUN ln -sf /dev/stdout /var/log/nginx/access.log && ln -sf /dev/stderr /var/log/nginx/error.log

RUN rm -fr /usr/share/nginx/www && \
wget --progress=dot:giga --no-check-certificate http://github.com/roundcube/roundcubemail/releases/download/$ROUNDCUBE_VERSION/roundcubemail-${ROUNDCUBE_VERSION}-complete.tar.gz -O - | tar xz && \
mv /root/roundcubemail-$ROUNDCUBE_VERSION /usr/share/nginx/www  && \
rm -Rf /usr/share/nginx/www/installer

WORKDIR /usr/share/nginx/www
RUN composer install --no-dev

COPY config.inc.php /usr/share/nginx/www/config/
COPY default /etc/nginx/sites-enabled/default
COPY launch.sh /root/
COPY php-fpm.ini /etc/php/7.4/fpm/php.ini
RUN nginx -c /etc/nginx/nginx.conf -t

COPY autologon.php /usr/share/nginx/www/plugins/autologon/autologon.php
CMD [ "bash", "/root/launch.sh" ]
