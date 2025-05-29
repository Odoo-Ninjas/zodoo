#
# Chrome Dockerfile
#
# https://github.com/dockerfile/chrome
#
TOTAL BROKEN

# Pull base image.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# Install Chromium.
RUN \
  apt-get update -y && \
  apt-get install -y apt-utils wget openssh-server \
  libnspr4 libnss3 fonts-liberation \
  fonts-wqy-microhei tightvncserver 
RUN apt-get update && apt-get install -y curl gnupg ca-certificates

# COPY Google's official GPG key securely
RUN curl -fsSL https://dl.google.com/linux/linux_signing_key.pub | \
    gpg --dearmor -o /usr/share/keyrings/google-chrome-keyring.gpg

# COPY Google Chrome repository
RUN echo "deb [signed-by=/usr/share/keyrings/google-chrome-keyring.gpg] http://dl.google.com/linux/chrome/deb/ stable main" | \
    tee /etc/apt/sources.list.d/google-chrome.list > /dev/null

# Update package lists and install Google Chrome
RUN apt-get update && apt-get install -y google-chrome-stable



RUN \
  groupadd -g 1000 user1 && \
  useradd -u 1000 -g 1000 -m -d /data user1 

RUN \
  mkdir -p /var/run/sshd && \
  sed -ri 's/UsePAM yes/#UsePAM yes/g' /etc/ssh/sshd_config && \
  sed -ri 's/#Port 22/Port 5800/g' /etc/ssh/sshd_config 

#RUN apt install -y xfce4 xfce4-goodies x11vnc xvfb
RUN apt install -y fluxbox


#RUN rm -rf /var/lib/apt/lists/* 

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
CMD ./cmd.sh
