#!/bin/bash
# Runs ON THE PROXMOX HOST. Installs einkdash into the container, checks
# it actually works, and rolls back if it doesn't.
#
#   CTID=200 bash deploy.sh
#
# Every .py file found in the payload gets installed, so adding a new
# module needs no change here.

set -euo pipefail

CTID="${CTID:-102}"
SRC="${SRC:-/tmp/einkdash-deploy}"
ZIP="${ZIP:-/tmp/einkdash.zip}"
APP="${APP:-/opt/einkdash}"
CONF_DIR="${CONF_DIR:-/etc/einkdash}"
SERVICE="${SERVICE:-einkdash-server}"
BACKUP="${BACKUP:-/opt/einkdash.prev}"
PORT="${PORT:-8080}"

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m  ok\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m!! \033[0m %s\n' "$*" >&2; exit 1; }

inct() { pct exec "$CTID" -- "$@"; }

# ---------------------------------------------------------------- checks
say "checking container $CTID"
pct status "$CTID" >/dev/null 2>&1 || die "container $CTID does not exist"
[ "$(pct status "$CTID")" = "status: running" ] || die "container $CTID is not running"
ok "container up"

[ -f "$ZIP" ] || die "payload not found: $ZIP"

# ---------------------------------------------------------------- unpack
say "unpacking payload"
command -v unzip >/dev/null || apt-get install -y unzip >/dev/null
rm -rf "$SRC"; mkdir -p "$SRC"
unzip -oq "$ZIP" -d "$SRC"

# Windows round-trips leave CRLF, which python tolerates but shell does not.
# Strip it from everything; harmless on files that never had it.
find "$SRC" -type f \( -name '*.py' -o -name '*.sh' -o -name '*.service' \
     -o -name '*.ini' -o -name '*.example' -o -name '*.conf' \) \
     -exec sed -i 's/\r$//' {} +

PY_FILES=$(cd "$SRC" && ls *.py 2>/dev/null || true)
[ -n "$PY_FILES" ] || die "no .py files in payload"
ok "found: $(echo "$PY_FILES" | tr '\n' ' ')"

# ---------------------------------------------------------------- backup
say "backing up current install"
inct sh -c "rm -rf $BACKUP; [ -d $APP ] && cp -a $APP $BACKUP || mkdir -p $BACKUP"
ok "previous version saved to $BACKUP"

# ---------------------------------------------------------------- install
say "installing"
inct mkdir -p "$APP" "$CONF_DIR"

# Runtime state (currently just history.json for the sparkline) has to
# live somewhere the unprivileged einkdash user can write -- CONF_DIR
# is root-owned on purpose, since it holds the API token.
STATE_DIR="${STATE_DIR:-/var/lib/einkdash}"
inct mkdir -p "$STATE_DIR"
inct chown einkdash:einkdash "$STATE_DIR"
for f in $PY_FILES; do
    pct push "$CTID" "$SRC/$f" "$APP/$f" --perms 644
    printf '     %s\n' "$f"
done

# The service unit only gets replaced if it actually changed.
if [ -f "$SRC/einkdash-server.service" ]; then
    pct push "$CTID" "$SRC/einkdash-server.service" \
        /tmp/einkdash-server.service --perms 644
    if ! inct cmp -s /tmp/einkdash-server.service \
            /etc/systemd/system/einkdash-server.service; then
        inct cp /tmp/einkdash-server.service /etc/systemd/system/
        inct systemctl daemon-reload
        ok "service unit updated"
    fi
fi

# NEVER touch config.ini -- it holds the API token. Ship the example so
# new options are visible, and diff it so you know when to look.
if [ -f "$SRC/config.ini.example" ]; then
    pct push "$CTID" "$SRC/config.ini.example" \
        "$CONF_DIR/config.ini.example" --perms 644
    if inct test -f "$CONF_DIR/config.ini"; then
        NEW_KEYS=$(inct sh -c "grep -oP '^\s*\[\K[^]]+' $CONF_DIR/config.ini.example | sort > /tmp/a; grep -oP '^\s*\[\K[^]]+' $CONF_DIR/config.ini | sort > /tmp/b; comm -23 /tmp/a /tmp/b" || true)
        if [ -n "$NEW_KEYS" ]; then
            printf '\033[1;33m  !! config.ini is missing section(s):\033[0m %s\n' \
                "$(echo "$NEW_KEYS" | tr '\n' ' ')"
        fi
    fi
fi
ok "files in place"

# ------------------------------------------------------------ compile check
# Catch syntax errors BEFORE restarting, so a typo never takes the
# service down.
say "compile check"
if ! inct python3 -m compileall -q "$APP" >/dev/null 2>&1; then
    inct python3 -m compileall "$APP" || true
    say "rolling back"
    inct sh -c "rm -rf $APP && cp -a $BACKUP $APP"
    inct systemctl restart "$SERVICE" || true
    die "syntax error - rolled back, service untouched"
fi
ok "compiles clean"

# ------------------------------------------------------------ render check
# A file can compile and still fail to draw. Render once before we
# restart anything. Run as the einkdash user, not root -- pct exec is
# root by default, and a root-run render would leave state_dir files
# root-owned, which then locks the real (unprivileged) service out of
# its own history.json on the next write. Running as einkdash here also
# means this check actually exercises the permissions the service will
# have, instead of masking permission bugs behind root's blanket access.
# /tmp is sticky-bit: a leftover file from any older root-run deploy
# blocks einkdash from overwriting it even though it can create new
# files there, so clear it first every time.
inct rm -f /tmp/einkdash-preview.png
RENDER_CMD="runuser -u einkdash -- python3 $APP/server.py -c $CONF_DIR/config.ini --once /tmp/einkdash-preview.png"
if ! inct sh -c "$RENDER_CMD" >/dev/null 2>&1; then
    inct sh -c "$RENDER_CMD" || true
    say "rolling back"
    inct sh -c "rm -rf $APP && cp -a $BACKUP $APP"
    inct systemctl restart "$SERVICE" || true
    die "render failed - rolled back"
fi
pct pull "$CTID" /tmp/einkdash-preview.png /tmp/einkdash-preview.png 2>/dev/null || true
ok "render ok -> /tmp/einkdash-preview.png (on this host)"

# Backstop: if anything above still touched state_dir as root (or a
# past deploy left it that way), fix ownership before restarting the
# real service.
inct chown -R einkdash:einkdash "$STATE_DIR"

# ---------------------------------------------------------------- restart
say "restarting $SERVICE"
inct systemctl restart "$SERVICE"

for i in $(seq 1 15); do
    if inct curl -sf -m 3 -o /dev/null http://localhost:$PORT/health; then
        ok "service healthy after ${i}s"
        HEALTHY=1
        break
    fi
    sleep 1
done

if [ -z "${HEALTHY:-}" ]; then
    say "service did not come up - rolling back"
    inct sh -c "rm -rf $APP && cp -a $BACKUP $APP"
    inct systemctl restart "$SERVICE"
    inct journalctl -u "$SERVICE" -n 30 --no-pager || true
    die "rolled back to previous version"
fi

# Fetch through the real endpoint, exactly as the Kindle does.
if inct curl -sf -m 20 -o /tmp/check.png "http://localhost:$PORT/dash.png?batt=87"; then
    SIZE=$(inct stat -c %s /tmp/check.png)
    ok "dash.png served (${SIZE} bytes)"
else
    printf '\033[1;33m  !! /health ok but dash.png failed - check the logs\033[0m\n'
fi

say "done. rollback available: pct exec $CTID -- sh -c 'rm -rf $APP && cp -a $BACKUP $APP && systemctl restart $SERVICE'"
