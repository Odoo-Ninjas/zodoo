#
# Chrome Dockerfile
#
# https://github.com/dockerfile/chrome
#
TOTAL BROKEN

# Pull base image.
FROM ubuntu:24.04

#___SNIPPET_APT_PROXY___

# Install Chromium.
RUN \
  #___SNIPPET_APT_INSTALL___ \
  apt-utils wget openssh-server \
  libnspr4 libnss3 fonts-liberation \
  fonts-wqy-microhei tightvncserver  \
  curl gnupg ca-certificates fluxbox \
  chromium

RUN \
  groupadd -g 1000 user1 && \
  useradd -u 1000 -g 1000 -m -d /data user1 

RUN \
  mkdir -p /var/run/sshd && \
  sed -ri 's/UsePAM yes/#UsePAM yes/g' /etc/ssh/sshd_config && \
  sed -ri 's/#Port 22/Port 5800/g' /etc/ssh/sshd_config 

RUN rm -rf /var/lib/apt/lists/* 

WORKDIR /data

# password is odoo3000
RUN mkdir .vnc
COPY vncconfig/ .vnc/
COPY fluxbox/ .fluxbox/
COPY cmd.sh cmd.sh
ENV USER=user1

# Define default command.
RUN \
chmod a+x cmd.sh && \
chmod a+x .vnc/xstartup && \
chown user1 . -R

USER user1
CMD ["./cmd.sh"]
