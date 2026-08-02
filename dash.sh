#!/bin/sh
# einkdash - Kindle side. Wake, fetch, blit, deep sleep, repeat.
# Lives at /mnt/us/extensions/einkdash/bin/dash.sh

DIR=$(dirname "$0")
CONF="$DIR/../einkdash.conf"
[ -f "$CONF" ] && . "$CONF"

: "${SERVER:=http://192.168.1.50:8080/dash.png}"
: "${INTERVAL:=1800}"      # seconds between refreshes
: "${FULL_EVERY:=4}"       # full (flashing) refresh every N updates
: "${WIFI_TIMEOUT:=45}"
: "${STOP_FRAMEWORK:=1}"   # set 0 for the first test run - see KINDLE.md

PNG=/tmp/einkdash.png
LOG=/mnt/us/extensions/einkdash/dash.log
PIDFILE=/tmp/einkdash.pid

echo $$ > "$PIDFILE"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"
    # keep the log from eating the filesystem
    tail -n 500 "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG"
}

# The reader UI will happily repaint over us, so shut it down. Note that
# this also removes KUAL, so read the "getting back out" section of
# KINDLE.md before you set STOP_FRAMEWORK=1.
if [ "$STOP_FRAMEWORK" = "1" ]; then
    stop framework  >/dev/null 2>&1 || stop lab126_gui >/dev/null 2>&1
    stop otaupd     >/dev/null 2>&1
    sleep 2
fi

# rtc index varies by model
RTC=/sys/class/rtc/rtc1/wakealarm
[ -e "$RTC" ] || RTC=/sys/class/rtc/rtc0/wakealarm

/usr/sbin/eips -c
/usr/sbin/eips -c        # known quirk: first clear often doesn't take
/usr/sbin/eips 2 2 "einkdash starting..."
log "started, server=$SERVER interval=${INTERVAL}s rtc=$RTC"

n=0
while true; do
    lipc-set-prop com.lab126.cmd wirelessEnable 1 >/dev/null 2>&1

    i=0
    while [ "$i" -lt "$WIFI_TIMEOUT" ]; do
        state=$(lipc-get-prop com.lab126.wifid cmState 2>/dev/null)
        [ "$state" = "CONNECTED" ] && break
        sleep 1
        i=$((i + 1))
    done

    BATT=$(gasgauge-info -c 2>/dev/null | tr -d '% ')
    [ -z "$BATT" ] && BATT=0

    if curl -sf -m 60 -o "$PNG.new" "$SERVER?batt=$BATT"; then
        mv "$PNG.new" "$PNG"
        log "fetch ok (batt ${BATT}%, wifi ${i}s)"
    else
        rm -f "$PNG.new"
        log "fetch FAILED (wifi ${i}s, state=$state)"
    fi

    # radio off before sleeping - it is the biggest drain by far
    lipc-set-prop com.lab126.cmd wirelessEnable 0 >/dev/null 2>&1

    if [ -f "$PNG" ]; then
        if [ "$n" -eq 0 ]; then
            /usr/sbin/eips -f -g "$PNG"     # full refresh, clears ghosting
        else
            /usr/sbin/eips -g "$PNG"        # partial, no flash
        fi
    fi
    n=$(( (n + 1) % FULL_EVERY ))

    # deep sleep until the rtc alarm fires
    echo 0 > "$RTC"
    echo "+$INTERVAL" > "$RTC"
    echo mem > /sys/power/state
    sleep 5                                  # settle after wake
done
