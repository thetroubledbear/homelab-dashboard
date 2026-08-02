# Deploying einkdash

One command from your Windows box:

```powershell
.\deploy.ps1
```

Or, while iterating on the layout:

```powershell
.\deploy.ps1 -Preview      # pulls the rendered PNG back and opens it
```

That's the whole loop. Edit `render_kindle.py`, run it, look at the
preview. The Kindle picks up changes on its next wake — you never touch
the device.

## What it does

`deploy.ps1` zips the deployable files, ships them to the Proxmox host
along with `deploy.sh`, and runs it there. `deploy.sh` does the work
inside the container:

1. **Checks** the container exists and is running.
2. **Unpacks** and strips CRLF from everything — the single most common
   Windows round-trip failure.
3. **Backs up** the current `/opt/einkdash` to `/opt/einkdash.prev`.
4. **Installs** every `.py` in the payload.
5. **Compile-checks** with `compileall`. On failure: restores the backup
   and exits *without* restarting. Your service never went down.
6. **Test-renders** one PNG. Code can compile and still fail to draw — a
   bad font path or a coordinate that throws only with real data. Same
   rollback on failure.
7. **Restarts** and polls `/health` for 15 seconds. If it never answers,
   restores the backup, restarts, and dumps the last 30 journal lines.
8. **Fetches `/dash.png`** through the real endpoint, exactly as the
   Kindle does.

Steps 5–7 mean a typo costs you an error message rather than a dead
dashboard on the wall.

## Adding new modules

Just drop a new `.py` in the folder. Both scripts glob for `*.py` — no
lists to maintain. `deploy.ps1` skips `render.py`, `dashboard.py` and
`preview.py`, which belong to the Waveshare build rather than the server.

## Config

`config.ini` is **never overwritten** — it holds your API token. The
example file is installed alongside it, and if it gains a section your
live config lacks, you get:

```
  !! config.ini is missing section(s): sensors
```

That's the prompt to open `config.ini.example` and copy the new block
across. It won't stop the deploy.

## Options

```powershell
.\deploy.ps1 -WhatIf                        # list what would be sent, send nothing
.\deploy.ps1 -PveHost 192.168.1.232 -Ctid 200
.\deploy.ps1 -Preview
```

Edit the defaults at the top of the `param()` block so you can just run
`.\deploy.ps1`.

## Manual rollback

The script prints this on success, and it's always available:

```bash
pct exec 200 -- sh -c 'rm -rf /opt/einkdash && cp -a /opt/einkdash.prev /opt/einkdash && systemctl restart einkdash-server'
```

Only one generation is kept. If you want more history, put the folder in
git inside the container.

## Running deploy.sh directly

If you're already on the Proxmox host — no PowerShell involved:

```bash
CTID=200 bash /tmp/deploy.sh
```

It expects the payload at `/tmp/einkdash.zip`. Every path is
env-overridable (`APP`, `CONF_DIR`, `SERVICE`, `BACKUP`, `PORT`), which
is also how the failure paths were tested.

## What this doesn't cover

The Kindle-side files (`dash.sh`, `stop.sh`, `einkdash.conf`,
`menu.json`, `config.xml`) still go over USB. They change rarely, and the
device isn't reachable when it's asleep. If you set up USBNetwork you
could `scp` to it while awake, but the wake window is short — USB stays
easier.

## Prerequisites

- OpenSSH client on Windows (`Get-Command ssh` to check; otherwise
  Settings → System → Optional Features → OpenSSH Client)
- SSH key auth to the Proxmox host, or you'll type the password three
  times per deploy:
  ```powershell
  ssh-keygen -t ed25519
  type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh root@192.168.1.232 "cat >> ~/.ssh/authorized_keys"
  ```
