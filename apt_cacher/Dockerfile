FROM debian:jessie
MAINTAINER Jack Sullivan

# Install squid-deb-proxy
RUN apt-get update -y && \
    apt-get install -y --no-install-recommends \
      squid-deb-proxy \
      squid-deb-proxy-client && \
    apt-get clean

# Copy init script
COPY entrypoint.sh /data/entrypoint.sh
RUN chmod +x /data/entrypoint.sh

# Handle user and paths
RUN ln -sf /data/squid/cache /var/cache/squid-deb-proxy
RUN ln -sf /data/squid/log/access.log /var/log/squid-deb-proxy/access.log
RUN ln -sf /data/squid/log/store.log /var/log/squid-deb-proxy/store.log
RUN ln -sf /data/squid/log/cache.log /var/log/squid-deb-proxy/cache.log
RUN ln -sf /data/squid/etc/extra-sources.acl /etc/squid-deb-proxy/mirror-dstdomain.acl.d/20-extra-sources.acl

EXPOSE 8000/tcp

ENTRYPOINT ["/data/entrypoint.sh"]
