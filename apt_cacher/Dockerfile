FROM debian:bullseye

# Install squid-deb-proxy
RUN apt-get update -y && \
    apt-get install -y --no-install-recommends \
      squid-deb-proxy \
      squid-deb-proxy-client && \
    apt-get clean

# Copy init script
COPY entrypoint.sh /data/entrypoint.sh
COPY squid/etc/extra-sources.acl /data/squid/etc/extra-sources.acl
COPY squid/etc/mirror-dstdomain.acl.d/* /data/squid/etc/mirror-dstdomain.acl.d
RUN chmod +x /data/entrypoint.sh

# Handle user and paths
RUN ln -sf /data/squid/cache /var/cache/squid-deb-proxy
RUN ln -sf /data/squid/log/access.log /var/log/squid-deb-proxy/access.log
RUN ln -sf /data/squid/log/store.log /var/log/squid-deb-proxy/store.log
RUN ln -sf /data/squid/log/cache.log /var/log/squid-deb-proxy/cache.log
RUN ln -sf /data/squid/etc/extra-sources.acl /etc/squid-deb-proxy/mirror-dstdomain.acl.d/20-extra-sources.acl

EXPOSE 8000/tcp

ENTRYPOINT ["/bin/bash", "/data/entrypoint.sh"]
COPY container_settings /opt/container_settings
