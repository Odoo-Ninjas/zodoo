FROM openresty/openresty:alpine
# Install Python3 + pip
RUN apk add --no-cache \
    python3 \
    py3-pip
EXPOSE 80
COPY run.sh /run.sh
COPY nginx.conf /usr/local/openresty/nginx/conf/nginx.conf
COPY static/ /usr/local/openresty/nginx/static/
COPY lua/ /usr/local/openresty/nginx/lua/
COPY conf.d/ /usr/local/openresty/nginx/conf.d/
COPY lua/myngx.lua /usr/local/openresty/luajit/share/lua/5.1/myngx.lua
COPY lua/basicauth.lua /usr/local/openresty/luajit/share/lua/5.1/basicauth.lua
COPY lua/dashauth.lua /usr/local/openresty/luajit/share/lua/5.1/dashauth.lua
COPY bin/ /usr/local/bin/
COPY construction_site/ /opt/construction_site/
RUN chmod a+x /usr/local/bin/* && \
    chmod a+rw -R /usr/local/openresty && \
    chown nobody:nobody -R /usr/local/openresty


CMD ["/bin/sh", "/run.sh"]
