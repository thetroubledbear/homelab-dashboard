"""Rolling sample history for the dashboard's sparkline strip.

A small JSON file next to config.ini -- CONF_DIR survives deploys and
rollbacks (deploy.sh only ever rewrites $APP), so the trend line
doesn't reset every time you push a layout tweak.
"""

import json
import time

MAX_SAMPLES = 600     # hard cap regardless of window, keeps the file small


def load(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return []


def record(path, cpu_pct, mem_pct, window_hours):
    """Append a sample, drop anything outside the window, save, return it."""
    samples = load(path)
    samples.append({"t": time.time(), "cpu": cpu_pct, "mem": mem_pct})
    cutoff = time.time() - window_hours * 3600
    samples = [s for s in samples if s["t"] >= cutoff][-MAX_SAMPLES:]
    with open(path, "w") as fh:
        json.dump(samples, fh)
    return samples
