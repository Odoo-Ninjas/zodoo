FROM ubuntu:22.04
ARG TARGETARCH

ENV DEBIAN_FRONTEND=noninteractive
ENV DISPLAY=:100
ENV TARGETARCH=${TARGETARCH}

# Install packages
RUN #___SNIPPET_APT_INSTALL___ \
    dbus-x11 \
    curl \
    net-tools \
    x11-utils \
    x11-xserver-utils \
    ca-certificates \
    fluxbox \
    tigervnc-viewer \
    tightvncserver

#___SNIPPET_XPRA_INSTALL___

# Set up minimal X session
RUN mkdir -p /root/.xpra
RUN echo "fluxbox &" > /root/.xsession

# Startup script
COPY entrypoint.sh /usr/local/bin/start-xpra
RUN chmod +x /usr/local/bin/start-xpra

COPY start.sh /start.sh

RUN #___SNIPPET_APT_INSTALL___ \
    tigervnc-common
# Entrypoint
ENTRYPOINT ["start-xpra"]