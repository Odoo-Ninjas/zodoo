FROM openresty/openresty:alpine
COPY nginx.conf /usr/local/openresty/nginx/conf/nginx.conf

EXPOSE 80
COPY run.sh /run.sh

CMD ["/bin/sh", "/run.sh"]