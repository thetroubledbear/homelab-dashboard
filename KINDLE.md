# einkdash on a Kindle 10 (KT4)

600×800, 16 greys, battery powered. The Kindle does no work beyond
fetching a PNG and blitting it — all the rendering happens in an LXC on
your Proxmox host, so you edit the layout over SSH on a real machine.

```
LXC on Proxmox                        Kindle
  polls Proxmox API                     wakes on rtc alarm
  renders 600x800 PNG      ────────▶    curl → /tmp/einkdash.png
  serves on :8080 (HTTP)                eips -g
                                        radio off, deep sleep 30 min
```

Plain HTTP is deliberate: the Kindle's TLS stack is from 2019 and can't
negotiate with anything modern. Bind the server to your LAN only, and
never expose it through your reverse proxy.

---

## Part 1 — the renderer (LXC)

Create a small Debian LXC on Proxmox (512 MB RAM, 4 GB disk is plenty),
then inside it:

```bash
apt update
apt install -y python3-pil python3-requests fonts-dejavu-core

useradd -r -s /usr/sbin/nologin einkdash
mkdir -p /opt/einkdash /etc/einkdash
cp proxmox.py render_kindle.py mascot.py server.py /opt/einkdash/
cp config.ini.example /etc/einkdash/config.ini
chmod 640 /etc/einkdash/config.ini
chown root:einkdash /etc/einkdash/config.ini
nano /etc/einkdash/config.ini
```

Fill in the Proxmox host, the API token you made earlier, your storage
names, and your service URLs. Then check it renders before involving the
Kindle at all:

```bash
python3 /opt/einkdash/server.py -c /etc/einkdash/config.ini --once /tmp/test.png
```

Copy `/tmp/test.png` somewhere you can look at it. If it says "No data
from Proxmox", fix that before going further — the token or the host is
wrong.

Then run it as a service:

```bash
cp einkdash-server.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now einkdash-server
curl -o /tmp/dash.png http://localhost:8080/dash.png
```

Note the LXC's IP — you need it in a moment.

---

## Part 2 — the Kindle

Copy the extension over USB to `/mnt/us/extensions/einkdash/`:

```
/mnt/us/extensions/einkdash/
├── config.xml
├── menu.json
├── einkdash.conf          <- edit SERVER to your LXC's IP
└── bin/
    ├── dash.sh
    └── stop.sh
```

Edit `einkdash.conf` and set `SERVER` to
`http://YOUR-LXC-IP:8080/dash.png`. **Leave `STOP_FRAMEWORK=0` for now.**

Eject, then open KUAL → einkdash → **Start dashboard**.

With `STOP_FRAMEWORK=0` the normal Kindle UI stays alive, so the reader
will eventually repaint over your dashboard — that's expected. What
you're checking is that the image appears at all, and that
`/mnt/us/extensions/einkdash/dash.log` shows `fetch ok`. Set
`INTERVAL=120` temporarily so you're not waiting half an hour between
attempts.

Once it's fetching reliably, set `STOP_FRAMEWORK=1` and `INTERVAL=1800`,
and restart it from KUAL. Now the reader UI is gone and the screen is
yours.

### Getting back out

This is the part to read before you set `STOP_FRAMEWORK=1`: **once the
framework is stopped, KUAL is gone too**, so "Stop dashboard" is no
longer reachable from the menu. Two ways back:

- **Reboot** — hold the power button for ~30 seconds. Everything returns
  to normal; the dashboard doesn't auto-start.
- **SSH** — if you install USBNetwork, you can `ssh` in and run
  `/mnt/us/extensions/einkdash/bin/stop.sh`, which kills the loop and
  restarts the UI without a reboot. Worth setting up if you plan to
  iterate.

### Auto-start on boot

Not enabled by default, deliberately — you want a boot that lands you in
a working Kindle while you're still tuning things. Once you're happy,
add an upstart job at `/etc/upstart/einkdash.conf` on the device.

---

## Tuning

| Setting | Where | Effect |
|---|---|---|
| `INTERVAL` | `einkdash.conf` | Seconds between refreshes. 1800 is a reasonable balance. |
| `FULL_EVERY` | `einkdash.conf` | Full flashing refresh every Nth update. Lower if ghosting builds up. |
| `refresh_minutes` | server `config.ini` | Only feeds the "next refresh" line in the footer — keep it in sync with `INTERVAL`. |
| `min_render_seconds` | server `config.ini` | Floor on how often Proxmox gets polled, regardless of requests. |

Battery: the KT4's cell is 900 mAh and yours is a few years old. Expect
roughly a week at 30-minute refreshes rather than the two-to-four weeks
you'll see quoted for Paperwhites. The radio is switched off between
refreshes, which is the single biggest saving. Keep the front light off.

Don't leave it permanently on the charger — old Kindle cells swell, and
a swollen battery behind the panel cracks it. Charge it monthly.

---

## Layout

```
┌──────────────────────────────────────┐
│ HOMELAB                        14:35 │  header
│ UP 12D 4H                            │
├──────────────────────────────────────┤
│   ╭───╮      ╭───╮      ╭───╮        │
│  ╱ 23  ╲    ╱ o_o ╲    ╱ 61  ╲       │  CPU / status core / RAM
│ │  CPU  │  │  SYS  │  │  RAM  │        dial gauges
│  ╲_____╱    ╲_____╱    ╲_____╱       │
│       LOAD 0.42 0.55 0.61            │
│⌐                                    ¬│
│ STORAGE                              │
│ local      [■■■□□□□□□]  38G/100G    │
│ local-lvm  [■■■■■□□□□]  210G/380G   │
│L                                    _│
│⌐                                    ¬│
│ CONTAINERS & VMS      6/7 UP         │
│ ● nextcloud (lxc)   ● paperless (lxc)│
│ ● npm (lxc)         ○ winvm (vm)     │
│L                                    _│
│⌐                                    ¬│
│ SERVICES                             │
│ ● Nextcloud         ● Paperless      │
│ ● NPM               ● Tailscale      │
│L                                    _│
├──────────────────────────────────────┤
│ UPD 14:35   NEXT 15:05        [██] 87%│
└──────────────────────────────────────┘
```

The layout flows from a vertical cursor rather than fixed coordinates,
and budgets the remaining space between the guest list and the services
block. Long guest lists get truncated with a `+ N more (2 down)` note
rather than pushing the footer off the screen. Up to 12 guests, 8
services, 3 storages and 2 ZFS pools are shown. Each section sits inside
reticle corner brackets, echoing the tick marks on the dial gauges above
it.

`mascot.py` draws a small robot head ("status core") centred between the
CPU and RAM dials, in the same tick-ring style. Same five moods, same
thresholds — only the art changed. It's no longer shared with any other
panel version; the old fixed-size 42×38 CRT-monitor icon and its
`draw_mascot(d, ox, oy, mood)` signature are gone.

A CPU trend sparkline sits below SERVICES when there's room for it (it's
the lowest-priority section and quietly skips itself rather than
overflow the footer). Samples persist to `state_dir/history.json`
(default `/var/lib/einkdash`), *not* `/etc/einkdash` — the service runs
as the unprivileged `einkdash` user, which can read `config.ini` but
can't write into CONF_DIR (root-owned, on purpose, since it holds the
API token). `deploy.sh` creates and chowns `state_dir` on every deploy.

## Iterating

On the LXC, `--once` renders straight to a file so you can adjust
`render_kindle.py` and look at the result without touching the Kindle:

```bash
python3 /opt/einkdash/server.py -c /etc/einkdash/config.ini --once /tmp/t.png
```

The Kindle picks up changes on its next wake — no redeployment.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `fetch FAILED` in dash.log | Wrong SERVER IP, or the LXC's firewall. Test with `curl` from another machine first. |
| Image appears then vanishes | `STOP_FRAMEWORK=0` — the reader UI repainted. Expected during testing. |
| Screen never updates, no log lines | Deep sleep isn't waking. Try the other rtc index, or replace the rtc block with plain `sleep $INTERVAL` (more drain, always works). |
| Heavy ghosting | Lower `FULL_EVERY` to 2. |
| Blank screen after start | Run `/usr/sbin/eips -c` manually over SSH; some firmware needs the clear twice, which `dash.sh` already does. |
| Kindle reboots into normal UI | Nothing auto-starts by design — relaunch from KUAL. |
