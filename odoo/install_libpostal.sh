#!/bin/bash
set -ex
if [[ "$ODOO_INSTALL_LIBPOSTAL" != "1" ]]; then
	exit 0
fi
apt-get update || exit -1
apt-get install -y \
python3 python3-venv git \
build-essential autoconf \
libtool curl automake \
python-dev pkg-config

WORKDIR=/usr/local/src/postal/code
DATADIR=/usr/local/src/postal/data

python3 -mvenv /root/postalenv
git clone https://github.com/openvenues/libpostal "$WORKDIR"
cd "$WORKDIR"
/root/postalenv/bin/python3 -mpip install nose
# 544d510db057678c16e70aa1b4598cd32d35242a
git checkout master
./bootstrap.sh
./configure --datadir="$DATADIR"
make -j4
make install
ldconfig
# /root/postalenv/bin/python3 install postal