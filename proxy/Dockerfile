FROM openresty/openresty:alpine
# Install Python3 + pip
RUN apk add --no-cache python3 py3-pip

EXPOSE 80
COPY run.sh /run.sh
COPY nginx.conf /usr/local/openresty/nginx/conf/nginx.conf
COPY static/ /usr/local/openresty/nginx/static/
COPY lua/ /usr/local/openresty/nginx/lua/
COPY conf.d/ /usr/local/openresty/nginx/conf.d/
COPY lua/myngx.lua /usr/local/openresty/luajit/share/lua/5.1/myngx.lua


CMD ["/bin/sh", "/run.sh"]