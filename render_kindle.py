"""600x800 8-bit greyscale dashboard for a Kindle 10 (KT4).

Portrait, native resolution, no rotation needed. Styled as a HUD/status
console: CPU and RAM read as tick-ring dial gauges flanking a robot
"status core" that carries the mascot's mood, and every list section
sits inside reticle corner brackets so the page reads as one instrument
cluster rather than a stack of separate widgets.

Layout uses a running y-cursor rather than hard-coded rows -- with this
much vertical space, hand-arithmetic on 40 coordinates is how you end up
with overlapping sections.
"""

import math
from datetime import datetime, timedelta
from PIL import Image, ImageDraw, ImageFont

import mascot

WIDTH, HEIGHT = 600, 800
MARGIN = 20
FOOTER_TOP = 748          # nothing may be drawn below this
ROW_H = 32                # one list row (guest / service)
DIAL_R = 52               # CPU/RAM/core dial radius
CHART_H = 56               # sparkline plot height (axis-label row is extra)
CHART_LABEL_H = 18

# 16-level e-ink; these all land on distinct greys
BLACK, DARK, MID, LIGHT, PALE, WHITE = 0, 68, 136, 187, 221, 255

FONT_DIR = "/usr/share/fonts/truetype/dejavu"
MONO = f"{FONT_DIR}/DejaVuSansMono.ttf"
MONO_B = f"{FONT_DIR}/DejaVuSansMono-Bold.ttf"


def _fonts():
    return {
        "host": ImageFont.truetype(MONO_B, 32),
        "clock": ImageFont.truetype(MONO_B, 28),
        "sub": ImageFont.truetype(MONO, 16),
        "section": ImageFont.truetype(MONO_B, 15),
        "body": ImageFont.truetype(MONO, 19),
        "small": ImageFont.truetype(MONO, 15),
        "dial_pct": ImageFont.truetype(MONO_B, 26),
        "dial_lbl": ImageFont.truetype(MONO_B, 13),
    }


def human_uptime(seconds):
    d, rem = divmod(int(seconds), 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return f"UP {d}D {h}H"
    if h:
        return f"UP {h}H {m}M"
    return f"UP {m}M"


def gib(n):
    g = n / (1024 ** 3)
    if g >= 1000:
        return f"{g / 1024:.1f}T"
    if g >= 100:
        return f"{g:.0f}G"
    return f"{g:.1f}G".replace(".0G", "G")


class Sheet:
    """Draw surface with a vertical cursor."""

    def __init__(self):
        self.img = Image.new("L", (WIDTH, HEIGHT), WHITE)
        self.d = ImageDraw.Draw(self.img)
        self.f = _fonts()
        self.y = 0

    # -- primitives --------------------------------------------------
    def tracked_text(self, xy, text, font, fill, spacing=2):
        """Manually letter-spaced text -- PIL has no tracking knob, and
        a little air between caps is most of what reads as "HUD" here."""
        x, y = xy
        for ch in text:
            self.d.text((x, y), ch, font=font, fill=fill)
            x += font.getbbox(ch)[2] + spacing
        return x

    def section(self, title):
        self.tracked_text((MARGIN + 12, self.y), title, self.f["section"],
                          MID, spacing=3)
        self.y += 26

    def reticle(self, top, size=9, shade=MID, w=2):
        """Corner brackets framing a section, echoing the dial ticks."""
        box = (MARGIN, top, WIDTH - MARGIN, self.y)
        x0, y0, x1, y1 = box
        for cx, cy, dx, dy in ((x0, y0, 1, 1), (x1, y0, -1, 1),
                               (x0, y1, 1, -1), (x1, y1, -1, -1)):
            self.d.line([cx, cy, cx + dx * size, cy], fill=shade, width=w)
            self.d.line([cx, cy, cx, cy + dy * size], fill=shade, width=w)

    def segmented_bar(self, x, y, w, h, pct, warn=False, n=18):
        gap = 3
        seg_w = (w - gap * (n - 1)) / n
        filled = round(n * max(0, min(100, pct)) / 100)
        for i in range(n):
            sx = x + i * (seg_w + gap)
            on = i < filled
            self.d.rectangle(
                [sx, y, sx + seg_w, y + h],
                fill=(BLACK if warn else DARK) if on else PALE,
                outline=MID if not on else None)

    def dot_blip(self, x, y, filled, r=6):
        """Crosshair blip when up, hollow ring when down."""
        d = self.d
        if filled:
            d.ellipse([x, y, x + r * 2, y + r * 2], fill=BLACK)
            d.line([x - 3, y + r, x + 2 * r + 3, y + r], fill=MID, width=1)
            d.line([x + r, y - 3, x + r, y + 2 * r + 3], fill=MID, width=1)
        else:
            d.ellipse([x, y, x + r * 2, y + r * 2], outline=MID, fill=WHITE,
                      width=2)

    def dial(self, cx, cy, r, pct, label, warn=False, ticks=20):
        d, f = self.d, self.f
        start, sweep = 135, 270
        for i in range(ticks + 1):
            a = math.radians(start + sweep * i / ticks)
            major = i % 5 == 0
            r0 = r - (10 if major else 5)
            x0, y0 = cx + r0 * math.cos(a), cy + r0 * math.sin(a)
            x1, y1 = cx + r * math.cos(a), cy + r * math.sin(a)
            d.line([x0, y0, x1, y1], fill=MID if major else PALE,
                  width=2 if major else 1)
        box = [cx - r - 16, cy - r - 16, cx + r + 16, cy + r + 16]
        d.arc(box, start=start, end=start + sweep, fill=PALE, width=3)
        fill_end = start + sweep * max(0, min(100, pct)) / 100
        d.arc(box, start=start, end=fill_end, fill=BLACK if warn else DARK,
             width=6)
        txt = f"{pct:.0f}"
        tb = f["dial_pct"].getbbox(txt)
        d.text((cx - (tb[2] - tb[0]) / 2, cy - 16), txt, font=f["dial_pct"],
               fill=BLACK)
        lb = f["dial_lbl"].getbbox(label)
        d.text((cx - (lb[2] - lb[0]) / 2, cy + 12), label,
               font=f["dial_lbl"], fill=MID)

    def sparkline(self, history, window_hours):
        """CPU trend over the last `window_hours`, area-filled, fixed
        0-100 scale so day-to-day renders stay visually comparable."""
        d, f = self.d, self.f
        x0, x1 = MARGIN + 12, WIDTH - MARGIN - 12
        y1 = self.y + CHART_H            # baseline
        y0 = self.y                      # 100% line

        if len(history) < 2:
            msg = "collecting history..."
            d.text((x0, y0 + CHART_H / 2 - 8), msg, font=f["small"],
                  fill=MID)
            self.y += CHART_H + CHART_LABEL_H
            return

        d.line([x0, y0, x1, y0], fill=PALE, width=1)
        mid_y = y0 + CHART_H / 2
        d.line([x0, mid_y, x1, mid_y], fill=PALE, width=1)
        d.line([x0, y1, x1, y1], fill=LIGHT, width=1)

        now = history[-1]["t"]
        oldest = now - window_hours * 3600
        span = max(now - oldest, 1)

        def pt(sample):
            px = x0 + (x1 - x0) * (sample["t"] - oldest) / span
            py = y1 - (y1 - y0) * max(0, min(100, sample["cpu"])) / 100
            return (px, py)

        pts = [pt(s) for s in history]
        d.polygon(pts + [(pts[-1][0], y1), (pts[0][0], y1)], fill=PALE)
        d.line(pts, fill=DARK, width=2)

        lx, ly = pts[-1]
        d.ellipse([lx - 3, ly - 3, lx + 3, ly + 3], fill=BLACK)
        tag = f"CPU {history[-1]['cpu']:.0f}%"
        tw = f["small"].getbbox(tag)[2]
        tx = min(lx + 8, x1 - tw)
        d.text((tx, ly - 18 if ly > y0 + 18 else ly + 6), tag,
              font=f["small"], fill=BLACK)

        d.text((x0, y1 + 4), f"-{window_hours}H", font=f["small"], fill=MID)
        nw = f["small"].getbbox("NOW")[2]
        d.text((x1 - nw, y1 + 4), "NOW", font=f["small"], fill=MID)

        self.y += CHART_H + CHART_LABEL_H


def quantize_16(img):
    """The panel shows 16 grey levels. Snapping to them ourselves gives
    predictable output instead of letting the device guess at our
    antialiased edges."""
    return img.point(lambda v: round(v / 17) * 17)


def _truncate(text, font, max_px):
    if font.getbbox(text)[2] <= max_px:
        return text
    while text and font.getbbox(text + "..")[2] > max_px:
        text = text[:-1]
    return text + ".."


def render(data, node_name="pve", services=None, battery=None,
           refresh_minutes=30, history=None, history_hours=6):
    services = services or []
    s = Sheet()
    d, f = s.d, s.f
    now = datetime.now()
    mood = mascot.pick_mood(data, services)

    # ---- header ----------------------------------------------------
    d.rectangle([0, 0, WIDTH, 70], fill=BLACK)
    s.tracked_text((MARGIN, 8), node_name.upper()[:14], f["host"], WHITE, 2)
    clock = now.strftime("%H:%M")
    cw = f["clock"].getbbox(clock)[2]
    d.text((WIDTH - MARGIN - cw, 10), clock, font=f["clock"], fill=WHITE)
    sub = human_uptime(data["uptime"]) if data else "HOST UNREACHABLE"
    s.tracked_text((MARGIN, 46), sub, f["sub"], PALE, 1)
    s.y = 100

    if not data:
        cx, cy = MARGIN + DIAL_R + 14, s.y + DIAL_R + 14
        mascot.draw_mascot(d, cx, cy, DIAL_R, mood, f["dial_lbl"])
        tx = cx + DIAL_R + 30
        d.text((tx, cy - 20), "No data from", font=f["body"], fill=BLACK)
        d.text((tx, cy + 4), "Proxmox.", font=f["body"], fill=BLACK)
        d.text((tx, cy + 34), "Check token, LXC", font=f["small"], fill=MID)
        d.text((tx, cy + 54), "and network.", font=f["small"], fill=MID)
        s.y = cy + DIAL_R + 30
        _footer(s, now, battery, refresh_minutes, stale=True)
        return quantize_16(s.img)

    # ---- dial row: CPU / status core / RAM --------------------------
    mem_pct = data["mem_used"] / max(data["mem_total"], 1) * 100
    # dial() draws its outer tick ring at r+16 beyond DIAL_R, so a plain
    # MARGIN inset here left the ring almost flush with the page edge.
    # Push the centers in by that overhang so the ring lines up with
    # everything else instead of the CPU/RAM dials themselves.
    DIAL_INSET = MARGIN + 16
    cx_l, cx_c, cx_r = DIAL_INSET + DIAL_R, WIDTH // 2, WIDTH - DIAL_INSET - DIAL_R
    cy = s.y + DIAL_R + 14
    s.dial(cx_l, cy, DIAL_R, data["cpu_pct"], "CPU", warn=data["cpu_pct"] >= 85)
    mascot.draw_mascot(d, cx_c, cy, DIAL_R - 10, mood, f["dial_lbl"])
    s.dial(cx_r, cy, DIAL_R, mem_pct, "RAM", warn=mem_pct >= 90)
    if data.get("loadavg"):
        load = "  ".join(f"{x:.2f}" for x in data["loadavg"][:3])
        lt = f"LOAD {load}"
        lb = f["small"].getbbox(lt)
        d.text((WIDTH / 2 - (lb[2] - lb[0]) / 2, cy + DIAL_R + 34), lt,
               font=f["small"], fill=MID)
    s.y = cy + DIAL_R + 58

    # ---- storage -----------------------------------------------------
    box_top = s.y
    s.section("STORAGE")
    for st in data["storage"][:3]:
        pct = st["used"] / max(st["total"], 1) * 100
        warn = pct >= 90
        d.text((MARGIN + 12, s.y), _truncate(st["name"], f["body"], 130),
               font=f["body"], fill=BLACK)
        s.segmented_bar(MARGIN + 150, s.y + 4, 220, 16, pct, warn=warn)
        d.text((MARGIN + 388, s.y),
               f"{gib(st['used'])}/{gib(st['total'])}",
               font=f["small"], fill=BLACK)
        s.y += 32

    for pool in data.get("zfs", [])[:2]:
        ok = pool["health"] == "ONLINE"
        s.dot_blip(MARGIN + 12, s.y + 3, ok, r=5)
        d.text((MARGIN + 30, s.y), f"zfs {pool['name']}", font=f["body"],
               fill=BLACK)
        d.text((MARGIN + 388, s.y), pool["health"], font=f["body"],
               fill=BLACK)
        s.y += 32

    s.y += 6
    s.reticle(box_top - 16)
    s.y += 26

    # ---- guests and services, sharing what's left ---------------------
    guests = ([("lxc", g) for g in data["guests"]["lxc"]]
              + [("vm", g) for g in data["guests"]["qemu"]])
    col_w = (WIDTH - 2 * MARGIN - 24) // 2

    # Services are few and always fit; reserve their block first, then
    # give every remaining row to the guest list.
    svc_rows = (min(len(services), 8) + 1) // 2
    svc_block = 42 + svc_rows * ROW_H + 26 if services else 0

    avail = FOOTER_TOP - s.y - 42 - svc_block
    max_rows = max(1, avail // ROW_H)
    shown = min(len(guests), max_rows * 2, 12)
    if shown < len(guests):                 # leave room for the "+N more"
        shown = min(shown, (max_rows - 1) * 2) if max_rows > 1 else shown

    up = sum(1 for _, g in guests if g["running"])
    box_top = s.y
    s.section(f"CONTAINERS & VMS  {up}/{len(guests)} UP")

    start_y = s.y
    for i, (kind, g) in enumerate(guests[:shown]):
        col, row = i % 2, i // 2
        x = MARGIN + 12 + col * col_w
        y = start_y + row * ROW_H
        s.dot_blip(x, y + 4, g["running"], r=5)
        d.text((x + 22, y), _truncate(f"{g['name']} ({kind})", f["body"],
                                      col_w - 34),
               font=f["body"], fill=BLACK if g["running"] else MID)
    s.y = start_y + ((shown + 1) // 2) * ROW_H
    if shown < len(guests):
        hidden_down = sum(1 for _, g in guests[shown:] if not g["running"])
        note = f"+ {len(guests) - shown} more"
        if hidden_down:
            note += f" ({hidden_down} down)"
        d.text((MARGIN + 12, s.y), note, font=f["small"], fill=MID)
        s.y += 24
    s.y += 6
    s.reticle(box_top - 16)
    s.y += 26

    if services:
        box_top = s.y
        s.section("SERVICES")
        start_y = s.y
        for i, (label, ok) in enumerate(services[:8]):
            col, row = i % 2, i // 2
            x = MARGIN + 12 + col * col_w
            y = start_y + row * ROW_H
            s.dot_blip(x, y + 4, ok, r=5)
            d.text((x + 22, y), _truncate(label, f["body"], col_w - 34),
                   font=f["body"], fill=BLACK if ok else MID)
        s.y = start_y + svc_rows * ROW_H + 6
        s.reticle(box_top - 16)
        s.y += 26

    # History is lowest priority: it only gets drawn if guests and
    # services left it enough room, never by squeezing them out. Matches
    # exactly what the section below draws: title + chart + pre-reticle pad.
    hist_block = 26 + (CHART_H + CHART_LABEL_H) + 6
    if history is not None and s.y + hist_block <= FOOTER_TOP:
        box_top = s.y
        s.section(f"CPU · LAST {history_hours}H")
        s.sparkline(history, history_hours)
        s.y += 6
        s.reticle(box_top - 16)

    _footer(s, now, battery, refresh_minutes)
    return quantize_16(s.img)


def _footer(s, now, battery, refresh_minutes, stale=False):
    d, f = s.d, s.f
    y0 = HEIGHT - 40
    d.rectangle([0, y0, WIDTH, HEIGHT], fill=BLACK)
    nxt = (now + timedelta(minutes=refresh_minutes)).strftime("%H:%M")
    left = f"UPD {now.strftime('%H:%M')}   NEXT {nxt}"
    d.text((MARGIN, y0 + 12), left, font=f["small"], fill=PALE)
    if battery is not None:
        bx, by = WIDTH - MARGIN - 46, y0 + 13
        d.rectangle([bx, by, bx + 36, by + 14], outline=PALE, width=2)
        d.rectangle([bx + 36, by + 4, bx + 39, by + 10], fill=PALE)
        fw = round(34 * max(0, min(100, battery)) / 100)
        d.rectangle([bx + 1, by + 1, bx + 1 + fw, by + 13], fill=PALE)
        txt = f"{battery}%"
        tw = f["small"].getbbox(txt)[2]
        d.text((bx - tw - 8, y0 + 12), txt, font=f["small"], fill=PALE)
