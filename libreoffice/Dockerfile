FROM debian:stretch
WORKDIR /usr/bin

#___SNIPPET_APT_PROXY___

# libreoffice
RUN apt-get update && \
apt-get install -q -y libreoffice libreoffice-writer ure libreoffice-java-common libreoffice-core libreoffice-common openjdk-8-jre fonts-opensymbol hyphen-fr hyphen-de hyphen-en-us hyphen-it hyphen-ru fonts-dejavu fonts-dejavu-core fonts-dejavu-extra fonts-droid-fallback fonts-dustin fonts-f500 fonts-fanwood fonts-freefont-ttf fonts-liberation fonts-lmodern fonts-lyx fonts-sil-gentium fonts-texgyre fonts-tlwg-purisa && \
apt-get -y -q remove libreoffice-gnome python3
CMD ["/usr/bin/python3", "/usr/bin/loop.py"]

COPY loop.py loop.py
