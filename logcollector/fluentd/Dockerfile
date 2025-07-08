FROM fluentd:v1.16-debian-1

USER root
#___SNIPPET_APT_PROXY___

#RUN ["apk", "add", "gcc", "g++"]
#RUN ["apk", "add", "ruby-dev"]
#RUN ["apk", "add", "libpq-dev"]

RUN apt-get update
RUN apt-get install -y build-essential
RUN apt-get install -y libpq-dev
RUN apt-get install -y python3-pip

#RUN ["gem", "install", "fluent-plugin-sql", "--no-document", "--version", "5.0.3"]
#RUN ["gem", "install", "fluent-plugin-nginx", "--no-document"]
RUN ["gem", "install", "fluent-plugin-sql", "--no-document"]
RUN ["gem", "install", "fluent-plugin-postgres", "--no-document"]
RUN ["gem", "install", "fluent-plugin-rewrite-tag-filter", "--no-document"]
#RUN ["gem", "install", "fluent-plugin-tail", "--no-document"]
RUN ["gem", "install", "pg", "--no-document"]
RUN pip install $PIP_OPTIONS fluent-logger --break-system-packages
RUN ["gem", "install", "fluent-plugin-json", "--no-document"]
RUN ["gem", "install", "fluent-plugin-docker-json", "--no-document"]
RUN ["gem", "install", "fluent-plugin-multi-format-parser", "--no-document"]
RUN ["gem", "install", "fluent-plugin-concat", "--no-document"]
RUN ["gem", "install", "fluent-plugin-multiline-parser", "--no-document"]
RUN ["gem", "install", "fluent-plugin-unix-client", "--no-document"]

RUN apt-get install -y sudo
RUN echo "#!/bin/bash\nchmod a+rwx /var/run/fluentd.sock -R" > /root/opensock.sh
RUN chmod a+x /root/opensock.sh
RUN echo "fluent ALL=NOPASSWD: /root/opensock.sh" >> /etc/sudoers
RUN sed -i '2 i rm -f /var/run/fluentd.sock/sock || true' /bin/entrypoint.sh
RUN sed -i '3 i sudo /root/opensock.sh' /bin/entrypoint.sh

USER fluent