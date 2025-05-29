FROM ubuntu:16.04
RUN apt-get update && apt-get install --no-install-recommends python python-pip -y && pip install --no-cache-dir pip --upgrade
RUN pip install --no-cache-dir  tinydb pudb
COPY sysroot/ /
RUN chmod a+x /usr/local/bin/run.py
VOLUME /opt
CMD PYTHONPATH=/usr/local/bin python /usr/local/bin/run.py
