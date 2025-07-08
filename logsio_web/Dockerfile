FROM node:12-bullseye
ARG LOGIO_RELATIVE_PATH
RUN apt-get update && apt-get install -y build-essential python2 python3 python3-pip
# in the application there is a PUBLIC_URL which is replaced by the relative part
# of the homepage section *facepalm*; the host doesnt matter
# ../ui/package.json "https://example.com$LOGIO_RELATIVE_PATH"
COPY requirements.txt .
RUN pip3 install $PIP_OPTIONS -r requirements.txt
RUN npm install -g typescript
COPY log.io /usr/local/src/log.io
WORKDIR /usr/local/src/log.io/server
RUN ./bin/build-ui.sh
RUN npm install
RUN npm update
RUN npm run build:js
RUN npm set strict-ssl false
RUN npm install -g log.io-file-input --unsafe-perm

ENV LOGIO_SERVER_CONFIG_PATH=/root/.log.io/server.json
ENV LOGIO_FILE_INPUT_CONFIG_PATH=/root/.log.io/file_input.json
COPY server.json "$LOGIO_SERVER_CONFIG_PATH"
COPY file_input.json "$LOGIO_FILE_INPUT_CONFIG_PATH"
COPY bin/run.sh /usr/local/bin
COPY bin/setup_container_logs_to_watch.py /usr/local/bin
RUN chmod a+x /usr/local/bin/run.sh /usr/local/bin/setup_container_logs_to_watch.py
CMD run.sh