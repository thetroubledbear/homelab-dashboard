"""A little robot status core that reacts to how the homelab is doing.

Drawn entirely with PIL primitives, sized to sit as the centre badge of
the dashboard's CPU/RAM dial pair -- same tick-ring language, so the
three read as one instrument cluster instead of a gauge plus a mascot
bolted on the side.
"""

import math

BLACK, DARK, MID, LIGHT, PALE, WHITE = 0, 68, 136, 187, 221, 255

MOODS = ("cool", "happy", "busy", "worried", "dead")


def pick_mood(data, services, storage_warn_pct=90):
    """Worst-case wins: anything actually broken outranks load."""
    if not data:
        return "dead"

    if any(up is not True for _, up in services):
        return "worried"

    guests = data["guests"]["lxc"] + data["guests"]["qemu"]
    if any(not g["running"] for g in guests):
        return "worried"

    if any(p["health"] not in ("ONLINE", "?") for p in data.get("zfs", [])):
        return "worried"

    for s in data.get("storage", []):
        if s["total"] and s["used"] / s["total"] * 100 >= storage_warn_pct:
            return "worried"

    cpu = data["cpu_pct"]
    mem = data["mem_used"] / max(data["mem_total"], 1) * 100
    if cpu >= 85 or mem >= 90:
        return "busy"
    if cpu < 20 and mem < 60:
        return "cool"
    return "happy"


def draw_mascot(d, cx, cy, r, mood, font_lbl, ticks=24, label="SYS"):
    """Robot head centred at (cx, cy), tick ring at radius r to match
    the CPU/RAM dials either side of it."""
    dashed = mood == "dead"          # broken ring reads as "offline"
    for i in range(ticks):
        if dashed and i % 2:
            continue
        a = math.radians(360 * i / ticks)
        major = i % (ticks // 4) == 0
        r0 = r - (9 if major else 5)
        x0, y0 = cx + r0 * math.cos(a), cy + r0 * math.sin(a)
        x1, y1 = cx + r * math.cos(a), cy + r * math.sin(a)
        d.line([x0, y0, x1, y1], fill=MID if major else PALE,
               width=2 if major else 1)
    d.ellipse([cx - r - 14, cy - r - 14, cx + r + 14, cy + r + 14],
              outline=PALE, width=3)

    pw, ph = 17, 13                  # face-plate half-extents
    px0, py0, px1, py1 = cx - pw, cy - ph, cx + pw, cy + ph

    # antenna, pokes out of the ring for a bit of character
    d.line([cx, py0 - 10, cx, py0], fill=BLACK, width=2)
    d.ellipse([cx - 3, py0 - 14, cx + 3, py0 - 8],
              outline=BLACK, width=2,
              fill=BLACK if mood != "dead" else WHITE)

    # ears
    d.rectangle([px0 - 5, cy - 5, px0 - 1, cy + 5], fill=BLACK)
    d.rectangle([px1 + 1, cy - 5, px1 + 5, cy + 5], fill=BLACK)

    d.rounded_rectangle([px0, py0, px1, py1], radius=6, outline=BLACK,
                        fill=WHITE, width=2)

    lx, rx = cx - 8, cx + 8
    ey = cy - 2
    my = cy + 7

    if mood == "dead":
        for ex in (lx, rx):
            d.line([ex - 3, ey - 3, ex + 3, ey + 3], fill=BLACK, width=2)
            d.line([ex - 3, ey + 3, ex + 3, ey - 3], fill=BLACK, width=2)
        d.line([lx - 2, my, rx + 2, my], fill=BLACK, width=2)

    elif mood == "worried":
        d.line([lx - 4, ey - 4, lx + 2, ey - 2], fill=BLACK, width=2)
        d.line([rx + 4, ey - 4, rx - 2, ey - 2], fill=BLACK, width=2)
        d.ellipse([lx - 2, ey, lx + 2, ey + 4], fill=BLACK)
        d.ellipse([rx - 2, ey, rx + 2, ey + 4], fill=BLACK)
        d.arc([lx - 3, my - 1, rx + 3, my + 8], start=180, end=360,
              fill=BLACK, width=2)
        d.line([px1 + 8, py0 - 2, px1 + 5, py0 + 5], fill=MID, width=2)

    elif mood == "busy":
        d.line([lx - 4, ey, lx + 4, ey], fill=BLACK, width=2)
        d.line([rx - 4, ey, rx + 4, ey], fill=BLACK, width=2)
        pts = [(lx - 5 + i * 3.3, my + (2.5 if i % 2 else -2.5))
               for i in range(6)]
        d.line(pts, fill=BLACK, width=2)

    elif mood == "cool":
        d.rounded_rectangle([lx - 7, ey - 3, rx + 7, ey + 3], radius=2,
                            fill=BLACK)
        d.line([lx - 1, ey - 1, lx + 2, ey - 2], fill=WHITE, width=1)
        d.arc([lx - 3, my - 4, rx + 3, my + 3], start=0, end=180,
              fill=BLACK, width=2)

    else:  # happy
        d.ellipse([lx - 2, ey - 2, lx + 2, ey + 2], fill=BLACK)
        d.ellipse([rx - 2, ey - 2, rx + 2, ey + 2], fill=BLACK)
        d.arc([lx - 4, my - 6, rx + 4, my + 3], start=0, end=180,
              fill=BLACK, width=2)

    if label:
        lb = font_lbl.getbbox(label)
        d.text((cx - (lb[2] - lb[0]) / 2, cy + r + 18), label,
               font=font_lbl, fill=MID)
