#!/usr/bin/env python3
"""Renders the dashboard on the Proxmox side and serves it as a PNG.

Runs in an LXC. The Kindle is a dumb display: it wakes, fetches this,
blits it, and goes back to sleep. Keeping the render here means you can
edit the layout over SSH on a real machine instead of poking at a
jailbroken e-reader.

Plain HTTP on purpose -- the Kindle's TLS stack is a decade old. Bind it
to the LAN only.
"""

import argparse
import configparser
import io
import logging
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from proxmox import ProxmoxClient, ProxmoxError  # noqa: E402
import history  # noqa: E402
import render_kindle  # noqa: E402

log = logging.getLogger("einkdash-server")

_cache = {"png": None, "at": 0.0, "batt": None}
_lock = threading.Lock()


def check_services(section, timeout=6):
    results = []
    for label, url in section.items():
        try:
            r = requests.get(url, timeout=timeout, verify=False,
                             allow_redirects=True)
            results.append((label, r.status_code < 400))
        except requests.RequestException:
            results.append((label, False))
    return results


def _history_path(cfg):
    """Separate from CONF_DIR on purpose: the service runs as the
    unprivileged `einkdash` user and can only read config.ini's
    directory, not write to it. state_dir must be writable by that
    user -- deploy.sh provisions the default."""
    state_dir = cfg["kindle"].get("state_dir", "/var/lib/einkdash")
    return os.path.join(state_dir, "history.json")


def build_png(cfg, battery, hist_path):
    px = cfg["proxmox"]
    storages = [s.strip() for s in px.get("storages", "local").split(",")
                if s.strip()]
    client = ProxmoxClient(
        host=px["host"], node=px["node"],
        token_id=px["token_id"], token_secret=px["token_secret"],
        verify_tls=px.getboolean("verify_tls", fallback=False),
    )
    try:
        data = client.fetch_all(storages)
    except ProxmoxError as exc:
        log.warning("proxmox fetch failed: %s", exc)
        data = None

    services = check_services(cfg["services"]) if cfg.has_section("services") \
        else []

    hist_hours = cfg["kindle"].getint("history_hours", fallback=6)
    if data:
        mem_pct = data["mem_used"] / max(data["mem_total"], 1) * 100
        samples = history.record(hist_path, data["cpu_pct"], mem_pct,
                                 hist_hours)
    else:
        samples = history.load(hist_path)

    img = render_kindle.render(
        data, node_name=px["node"], services=services, battery=battery,
        refresh_minutes=cfg["kindle"].getint("refresh_minutes", fallback=30),
        history=samples, history_hours=hist_hours,
    )
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def get_png(cfg, battery, hist_path):
    """One render per min_render_seconds, shared across requests."""
    min_age = cfg["kindle"].getint("min_render_seconds", fallback=60)
    with _lock:
        fresh = time.time() - _cache["at"] < min_age
        if _cache["png"] and fresh and _cache["batt"] == battery:
            log.debug("serving cached render")
            return _cache["png"]
        png = build_png(cfg, battery, hist_path)
        _cache.update(png=png, at=time.time(), batt=battery)
        return png


class Handler(BaseHTTPRequestHandler):
    cfg = None
    hist_path = None
    server_version = "einkdash"

    def log_message(self, fmt, *args):
        log.info("%s %s", self.address_string(), fmt % args)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path in ("/", "/dash.png"):
            q = parse_qs(url.query)
            battery = None
            if "batt" in q:
                try:
                    battery = int(float(q["batt"][0]))
                except (ValueError, IndexError):
                    battery = None
            try:
                png = get_png(self.cfg, battery, self.hist_path)
            except Exception as exc:
                log.exception("render failed")
                self.send_error(500, str(exc))
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(png)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(png)
        elif url.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok\n")
        else:
            self.send_error(404)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-c", "--config", default="/etc/einkdash/config.ini")
    ap.add_argument("--once", metavar="FILE",
                    help="render one PNG to FILE and exit (for testing)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s")

    cfg = configparser.ConfigParser()
    if not cfg.read(args.config):
        sys.exit(f"config not found: {args.config}")
    if not cfg.has_section("kindle"):
        cfg.add_section("kindle")

    hist_path = _history_path(cfg)

    if args.once:
        with open(args.once, "wb") as fh:
            fh.write(build_png(cfg, battery=87, hist_path=hist_path))
        print(f"wrote {args.once}")
        return

    Handler.cfg = cfg
    Handler.hist_path = hist_path
    host = cfg["kindle"].get("listen_host", "0.0.0.0")
    port = cfg["kindle"].getint("listen_port", fallback=8080)
    log.info("serving on %s:%s", host, port)
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
