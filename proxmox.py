"""Minimal read-only Proxmox VE API client.

Only needs the PVEAuditor role. Three requests give us everything the
dashboard shows, which keeps the Pi Zero's poll cheap.
"""

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class ProxmoxError(Exception):
    pass


class ProxmoxClient:
    def __init__(self, host, node, token_id, token_secret,
                 verify_tls=False, timeout=10):
        self.base = host.rstrip("/") + "/api2/json"
        self.node = node
        self.verify = verify_tls
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"PVEAPIToken={token_id}={token_secret}"
        })

    def _get(self, path, params=None):
        try:
            r = self.session.get(self.base + path, params=params,
                                 verify=self.verify, timeout=self.timeout)
            r.raise_for_status()
            return r.json().get("data")
        except requests.RequestException as exc:
            raise ProxmoxError(f"{path}: {exc}") from exc

    def node_status(self):
        """CPU load, memory, uptime for the node."""
        d = self._get(f"/nodes/{self.node}/status")
        mem = d.get("memory", {})
        raw_load = d.get("loadavg") or []
        try:
            load = [float(x) for x in raw_load]
        except (TypeError, ValueError):
            load = []
        return {
            "cpu_pct": (d.get("cpu") or 0) * 100,
            "mem_used": mem.get("used", 0),
            "mem_total": mem.get("total", 1),
            "uptime": d.get("uptime", 0),
            "loadavg": load,
        }

    def guests(self):
        """Every LXC and VM in one call, with running state."""
        rows = self._get("/cluster/resources", params={"type": "vm"}) or []
        out = {"lxc": [], "qemu": []}
        for r in rows:
            kind = r.get("type")
            if kind in out:
                out[kind].append({
                    "name": r.get("name", str(r.get("vmid"))),
                    "running": r.get("status") == "running",
                })
        return out

    def storage(self, wanted):
        """Usage for the named storages, in the order requested."""
        rows = self._get(f"/nodes/{self.node}/storage") or []
        by_name = {r.get("storage"): r for r in rows}
        out = []
        for name in wanted:
            r = by_name.get(name)
            if not r:
                continue
            out.append({
                "name": name,
                "used": r.get("used", 0),
                "total": r.get("total", 1),
            })
        return out

    def zfs_pools(self):
        """Pool health, if any ZFS pools exist. Safe to call before you
        have any -- returns an empty list on older setups or errors."""
        try:
            rows = self._get(f"/nodes/{self.node}/disks/zfs") or []
        except ProxmoxError:
            return []
        return [{"name": r.get("name"), "health": r.get("health", "?")}
                for r in rows]

    def fetch_all(self, storages):
        data = self.node_status()
        data["guests"] = self.guests()
        data["storage"] = self.storage(storages)
        data["zfs"] = self.zfs_pools()
        return data
