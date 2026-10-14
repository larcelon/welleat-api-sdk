FROM alpine:3.20
RUN apk add --no-cache squid \
    && mkdir -p /var/log/squid \
    && chown -R squid:squid /var/log/squid
COPY squid.conf /etc/squid/squid.conf
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 755 /usr/local/bin/entrypoint.sh
USER squid
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
