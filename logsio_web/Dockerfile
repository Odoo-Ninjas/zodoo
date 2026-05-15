FROM node:12-bullseye AS builder
ARG LOGIO_RELATIVE_PATH
#___SNIPPET_APT_PROXY___
RUN #___SNIPPET_APT_INSTALL___ build-essential python2 python3 python3-pip
# in the application there is a PUBLIC_URL which is replaced by the relative part
# of the homepage section *facepalm*; the host doesnt matter
# ../ui/package.json "https://example.com$LOGIO_RELATIVE_PATH"
COPY requirements.txt .
RUN pip3 install $(cat /etc/pip_options) -r requirements.txt
RUN npm install -g typescript
COPY log.io /usr/local/src/log.io
WORKDIR /usr/local/src/log.io/server
RUN ./bin/build-ui.sh
RUN npm install
RUN npm update
RUN npm run build:js
RUN npm prune --production
RUN npm set strict-ssl false
RUN npm install -g log.io-file-input --unsafe-perm

ENV LOGIO_SERVER_CONFIG_PATH=/root/.log.io/server.json
ENV LOGIO_FILE_INPUT_CONFIG_PATH=/root/.log.io/file_input.json
COPY server.json "$LOGIO_SERVER_CONFIG_PATH"
COPY file_input.json "$LOGIO_FILE_INPUT_CONFIG_PATH"
COPY bin/run.sh /usr/local/bin
COPY bin/setup_container_logs_to_watch.py /usr/local/bin
RUN chmod a+x /usr/local/bin/run.sh /usr/local/bin/setup_container_logs_to_watch.py

# cleanup in builder so the final COPY gets clean files
RUN apt-get purge -y gcc g++ build-essential python perl && \
apt-get autoremove -y && \
apt-get clean -y && \
rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/* /var/log/* \
/usr/share/doc /usr/share/man /usr/share/icons /usr/share/vim \
/usr/share/perl /usr/share/poppler /usr/share/locale \
/usr/lib/gcc /usr/lib/git-core /usr/include /var/cache \
/usr/lib/aarch*/libicu* /usr/lib/aarch*/perl /usr/lib/aarch*/perl-base \
/usr/lib/aarch*/gconv /usr/lib/python2.7 \
/usr/lib/python3/dist-packages/mercurial \
/usr/local/src/log.io/ui/node_modules \
/usr/local/src/log.io/server/src \
/root/.npm /var/lib/dpkg && \
npm cache clean --force 2>/dev/null || true && \
find / -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# --- Final stage: single layer copy ---
FROM node:12-bullseye-slim
ENV LOGIO_SERVER_CONFIG_PATH=/root/.log.io/server.json
ENV LOGIO_FILE_INPUT_CONFIG_PATH=/root/.log.io/file_input.json
WORKDIR /usr/local/src/log.io/server

COPY --from=builder / /

CMD ["run.sh"]
