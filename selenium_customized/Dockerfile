FROM ubuntu:22.04
ARG TARGETARCH
ENV DEBIAN_FRONTEND=noninteractive
ENV WORKDIR=/opt/robot
ENV ROBOT_THREADS=1
ENV PATH="$PATH:/opt/robot/.local/bin"



#___SNIPPET_APT_PROXY___

RUN #___SNIPPET_APT_INSTALL___ \
 ca-certificates gnupg wget sudo curl x11-utils python3-requests

#=========
# Firefox
#=========
ARG FIREFOX_VERSION=latest
ARG FIREFOX_DOWNLOAD_URL=""
ARG FIREFOX_LANG_VERSION=${FIREFOX_VERSION}
ENV FIREFOX_VERSION=${FIREFOX_VERSION}
ENV FIREFOX_DOWNLOAD_URL=${FIREFOX_DOWNLOAD_URL}
ARG FIREFOX_LANG_VERSION=${FIREFOX_LANG_VERSION}
COPY install-firefox-apt.sh /opt/bin/install-firefox-apt.sh
COPY install-firefox.sh /opt/bin/install-firefox.sh
RUN chmod +x /opt/bin/install-firefox.sh && \
    bash /opt/bin/install-firefox.sh

#============
# GeckoDriver
#============
ARG GECKODRIVER_VERSION=latest
ENV GECKODRIVER_VERSION=${GECKODRIVER_VERSION}
RUN LATEST_VERSION=$(curl -s -L -o /dev/null -w '%{url_effective}\n' https://github.com/mozilla/geckodriver/releases/latest | sed -E 's#.*/tag/(v[0-9.]+).*#\1#') \
  && DRIVER_ARCH=$(if [ "$(dpkg --print-architecture)" = "amd64" ]; then echo "linux64"; else echo "linux-aarch64"; fi) \
  && GK_VERSION=$(if [ ${GECKODRIVER_VERSION:-latest} = "latest" ]; then echo "${LATEST_VERSION}"; else echo $GECKODRIVER_VERSION; fi) \
  && echo "Using GeckoDriver version: "$GK_VERSION \
  && wget --no-verbose -O /tmp/geckodriver.tar.gz https://github.com/mozilla/geckodriver/releases/download/${GK_VERSION}/geckodriver-${GK_VERSION}-${DRIVER_ARCH}.tar.gz \
  && rm -rf /opt/geckodriver \
  && tar -C /opt -zxf /tmp/geckodriver.tar.gz \
  && rm /tmp/geckodriver.tar.gz \
  && mv /opt/geckodriver /opt/geckodriver-$GK_VERSION \
  && chmod 755 /opt/geckodriver-$GK_VERSION \
  && ln -fs /opt/geckodriver-$GK_VERSION /usr/bin/geckodriver

#==================
# XPRA
#========
#___SNIPPET_XPRA_INSTALL___

RUN #___SNIPPET_APT_INSTALL___ \
 x11-apps
RUN #___SNIPPET_APT_INSTALL___ \
	fluxbox
RUN mkdir -p /root/.xpra
RUN echo "fluxbox &" > /root/.xsession
COPY entrypoint.sh /usr/local/bin/entrypoint.sh

# Startup script
COPY maximize_all_windows.py /usr/local/bin/maximize_all_windows.py
COPY start.sh /usr/local/bin/start.sh

RUN \
chmod +x /usr/local/bin/entrypoint.sh && \
chmod +x /usr/local/bin/maximize_all_windows.py && \
chmod +x /usr/local/bin/start.sh 
ENV DISPLAY=:100
RUN mkdir -p /root/.fluxbox

COPY test_geckodriver.py /opt/test_geckodriver.py
COPY geckodriver_loop.sh /usr/local/bin/geckodriver_loop.sh



CMD ["/bin/bash", "/usr/local/bin/entrypoint.sh"]


ENV WEBDRIVER_KILLSWITCH_BINDING=0.0.0.0:4445
ADD http_kill_switch.py /usr/local/bin/http_kill_switch.py
ADD test_killswitch.sh /usr/local/bin/test_killswitch.sh
RUN #___SNIPPET_APT_INSTALL___ \
  python3 python3-pip python3-setuptools python3-wheel
RUN python3 -mpip install psutil