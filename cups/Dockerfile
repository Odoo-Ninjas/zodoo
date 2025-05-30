FROM debian:stretch

#___SNIPPET_APT_MIRRORS___
#___SNIPPET_APT_PROXY___

# Install cups
RUN \
apt-get update && \
apt-get install --no-install-recommends cups cups-pdf whois wget samba-client python3 python3-cups rsync python3-pip vim -y && \
apt-get clean && \
rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*
RUN pip3 install --no-cache-dir pip --upgrade && \
pip3 install --no-cache-dir pathlib

# Disbale some cups backend that are unusable within a container
RUN mv /usr/lib/cups/backend/parallel /usr/lib/cups/backend-available/
RUN mv /usr/lib/cups/backend/serial /usr/lib/cups/backend-available/
#RUN mv /usr/lib/cups/backend/usb /usr/lib/cups/backend-available/

COPY etc-cups/ /etc/cups.template/
VOLUME /var/spool/cups
VOLUME /var/cache/cups

COPY etc-pam.d-cups /etc/pam.d/cups
COPY print.py /print.py
RUN chmod a+x /print.py

COPY smbc /usr/lib/cups/backend/smbc
RUN chmod a+x /usr/lib/cups/backend/smbc

EXPOSE 631

COPY backup_printers.sh /backup_printers.sh
RUN chmod a+x /backup_printers.sh

COPY start_cups.sh /root/start_cups.sh
RUN chmod +x /root/start_cups.sh
CMD ["/root/start_cups.sh"]

# Trigger initial apply of configs; you can also map the /etc/cups directory to your own folder
RUN rm -Rf /etc/cups/cupsd.conf
RUN ls /etc/cups -lhtra

# install proprietary drivers
RUN dpkg --add-architecture i386
COPY drivers/ /drivers/
RUN ls -lhtra /drivers
RUN dpkg -i --force-all /drivers/ql720nwpdrv-3.1.5-0.i386.deb
RUN dpkg -i --force-all /drivers/ql820nwbpdrv-3.1.5-0.i386.deb
