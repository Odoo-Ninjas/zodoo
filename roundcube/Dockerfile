FROM    ubuntu:24.04
ENV     DEBIAN_FRONTEND=noninteractive
ENV     TERM=xterm
ENV     ROUNDCUBE_VERSION=1.6.0
ENV     MAIL_SERVER=mail
MAINTAINER Round Cube <rc@xxx.org>

WORKDIR /root
RUN mkdir -p /rc
RUN apt update
RUN apt -y upgrade
RUN apt search php.*7
RUN apt install -y php-net-ldap2 php-net-ldap3 \
php-imagick php8.3-common php8.3-gd php8.3-imap \
php8.3-curl php8.3-zip php8.3-xml php8.3-mbstring \
php8.3-bz2 php8.3-intl php8.3-gmp php8.3-fpm php8.3-sqlite3
RUN apt install -y nginx wget composer

RUN apt install -y python3-pip
RUN pip3 install wheel  pathlib --break-system-packages
RUN ln -sf /dev/stdout /var/log/nginx/access.log && ln -sf /dev/stderr /var/log/nginx/error.log

RUN rm -fr /usr/share/nginx/www && \
wget --no-check-certificate http://github.com/roundcube/roundcubemail/releases/download/$ROUNDCUBE_VERSION/roundcubemail-${ROUNDCUBE_VERSION}-complete.tar.gz -O - | tar xz && \
mv /root/roundcubemail-$ROUNDCUBE_VERSION /usr/share/nginx/www  && \
rm -Rf /usr/share/nginx/www/installer

WORKDIR /usr/share/nginx/www
RUN composer install --no-dev

ADD config.inc.php /usr/share/nginx/www/config/
ADD default /etc/nginx/sites-enabled/default
ADD launch.sh /root/
ADD php-fpm.ini /etc/php/8.3/fpm/php.ini
RUN nginx -c /etc/nginx/nginx.conf -t

COPY autologon.php /usr/share/nginx/www/plugins/autologon/autologon.php
CMD [ "bash", "/root/launch.sh" ]
