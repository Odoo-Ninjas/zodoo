# syntax=docker/dockerfile:1
ARG BASE_IMAGE=ubuntu:22.04
FROM ${BASE_IMAGE}
ARG ODOO_PYTHON_VERSION
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential zlib1g-dev make libssl-dev libffi-dev libsqlite3-dev \
      libjpeg-dev libcurl3-dev libxml2-dev libxslt1-dev libfreetype6-dev \
      libpng-dev libpcre3-dev liblzma-dev freetds-dev libbz2-dev ncurses-dev \
      rsync gcc curl ca-certificates tar \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/local/src
RUN curl -fsSL https://www.python.org/ftp/python/${ODOO_PYTHON_VERSION}/Python-${ODOO_PYTHON_VERSION}.tgz -o /usr/local/src/python.tgz \
 && tar xfz /usr/local/src/python.tgz \
 && rm /usr/local/src/python.tgz

WORKDIR /usr/local/src/Python-${ODOO_PYTHON_VERSION}
RUN ./configure --enable-optimizations >/dev/null \
 && make -j$(nproc) > /dev/null \
 && make install > /dev/null 2>&1

# /python mirrors the built source tree so downstream stages can run
# \"cd /opt/python && make install\" without recompiling.
RUN rsync /usr/local/src/Python-${ODOO_PYTHON_VERSION}/ /python -ar
