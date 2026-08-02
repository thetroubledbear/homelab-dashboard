#!/bin/sh
# Stop the dashboard and bring the normal Kindle UI back.
PIDFILE=/tmp/einkdash.pid
[ -f "$PIDFILE" ] && kill "$(cat "$PIDFILE")" 2>/dev/null
rm -f "$PIDFILE"
/usr/sbin/eips -c
start framework >/dev/null 2>&1 || start lab126_gui >/dev/null 2>&1
