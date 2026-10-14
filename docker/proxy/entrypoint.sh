#!/bin/sh
# Relaie le journal d'accès sur la sortie du conteneur puis lance squid au premier plan.
set -eu
touch /var/log/squid/access.log
tail -F /var/log/squid/access.log &
exec squid -N -d 1 -f /etc/squid/squid.conf
