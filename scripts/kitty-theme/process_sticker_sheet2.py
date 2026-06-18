#!/usr/bin/env python3
"""
Process the 8-pose rabbit sticker sheet (kitty2.png) into a Clawd theme
with SVG-based eye tracking for the idle state.

Usage:
    python3 process_sticker_sheet2.py <path-to-kitty2.png>
"""

import sys, os, math, json, shutil, tempfile
from pathlib import Path
from PIL import Image, ImageFilter, ImageDraw

# ──────────────────────────────────────────────
POSES = [
    (0, 0, "idle",          "neutral sitting"),
    (1, 0, "thinking",      "question mark"),
    (2, 0, "working",       "laptop"),
    (3, 0, "error",         "sweat drop"),
    (0, 1, "attention",     "sparkles"),
    (1, 1, "notification",  "exclamation"),
    (2, 1, "sleeping",      "zzz"),
    (3, 1, "waking",        "wink"),
]

# ──────────────────────────────────────────────
# Background removal
# ──────────────────────────────────────────────

def remove_background(img: Image.Image, tol: int = 40) -> Image.Image:
    img = img.convert("RGBA")
    pixels = img.load()
    w, h = img.size
    corners = [(5,5),(w-5,5),(5,h-5),(w-5,h-5)]
    bg = tuple(int(sum(img.getpixel(c)[i] for c in corners)/4) for i in range(3))

    def dist(c):
        return math.sqrt(sum((a-b)**2 for a,b in zip(c[:3], bg)))

    for y in range(h):
        for x in range(w):
            px = pixels[x,y]
            d = dist(px)
            if d < tol:
                pixels[x,y] = (px[0],px[1],px[2],0)
            elif d < tol*1.8:
                alpha = int(255*(d-tol)/(tol*0.8))
                pixels[x,y] = (px[0],px[1],px[2],min(alpha,px[3]))
    return img


# ──────────────────────────────────────────────
# Eye detection (finds two dark circles in upper half)
# ──────────────────────────────────────────────

def detect_eyes(cell: Image.Image):
    """
    Returns (lx, ly, rx, ry, radius) in pixel coords.
    Looks for two darkest symmetrical regions in the upper-center area.
    """
    w, h = cell.size
    gray = cell.convert("L")

    # Search region: x 20-80%, y 20-55%
    sx0, sx1 = int(w*0.15), int(w*0.85)
    sy0, sy1 = int(h*0.20), int(h*0.55)

    # Collect dark pixels
    pix = gray.load()
    dark = []
    for y in range(sy0, sy1):
        for x in range(sx0, sx1):
            if pix[x,y] < 80:  # dark pixels
                dark.append((x,y))

    if len(dark) < 20:
        # Fallback: assume symmetric eye positions
        lx, ly = int(w*0.37), int(h*0.35)
        rx, ry = int(w*0.63), int(h*0.35)
        radius = int(w*0.09)
        return lx, ly, rx, ry, radius

    # Cluster: split by x midpoint
    mid = w // 2
    left_pts  = [(x,y) for x,y in dark if x < mid]
    right_pts = [(x,y) for x,y in dark if x >= mid]

    def centroid(pts):
        if not pts:
            return None
        return (int(sum(p[0] for p in pts)/len(pts)),
                int(sum(p[1] for p in pts)/len(pts)))

    lc = centroid(left_pts)
    rc = centroid(right_pts)

    if lc is None or rc is None:
        lx, ly = int(w*0.37), int(h*0.35)
        rx, ry = int(w*0.63), int(h*0.35)
        radius = int(w*0.09)
        return lx, ly, rx, ry, radius

    lx, ly = lc
    rx, ry = rc
    # Estimate radius from spread
    radius = max(int(math.sqrt(len(left_pts)/math.pi)*0.9), int(w*0.06))
    return lx, ly, rx, ry, radius


# ──────────────────────────────────────────────
# SVG idle generator (with eye tracking)
# ──────────────────────────────────────────────

def make_idle_svg(cell: Image.Image, out_path: Path, vw: int, vh: int, padding: int):
    """
    Creates an SVG for idle state with eye tracking.
    Saves the character as a separate PNG (relative href — Electron can load it).
    """
    lx, ly, rx, ry, radius = detect_eyes(cell)
    print(f"    Eye detection: L=({lx},{ly}) R=({rx},{ry}) r={radius}")

    cw, ch = cell.size
    img_y = padding // 2

    # Save base image as separate PNG next to SVG
    base_png_name = "bunny-idle-base.png"
    base_png_path = out_path.parent / base_png_name
    cell.save(str(base_png_path), "PNG")

    pupil_color = "#1a1c2e"
    pupil_r = max(int(radius * 0.55), 6)
    ely = ly + img_y
    ery = ry + img_y

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {vw} {vh}">
  <g id="shadow-js">
    <ellipse cx="{vw//2}" cy="{vh-4}" rx="{int(cw*0.28)}" ry="4"
             fill="#000000" opacity="0.18"/>
  </g>

  <g id="body-js">
    <image href="{base_png_name}"
           x="0" y="{img_y}" width="{cw}" height="{ch}"
           image-rendering="optimizeQuality"/>
  </g>

  <g id="eyes-js">
    <circle cx="{lx}" cy="{ely}" r="{pupil_r}" fill="{pupil_color}" opacity="0.85"/>
    <circle cx="{rx}" cy="{ery}" r="{pupil_r}" fill="{pupil_color}" opacity="0.85"/>
  </g>
</svg>"""

    out_path.write_text(svg, encoding="utf-8")
    print(f"    → {out_path.name}  (SVG with eye tracking, base: {base_png_name})")


# ──────────────────────────────────────────────
# Animation frames
# ──────────────────────────────────────────────

def ease_in_out(t):
    return t*t*(3-2*t)

def make_frames(cell: Image.Image, state: str, padding: int):
    cw, ch = cell.size
    W, H = cw, ch + padding

    def frame(dy_f=0.0, dx_f=0.0, scale=1.0):
        max_dy = int(ch * 0.065)
        max_dx = int(cw * 0.04)
        dy = int(dy_f * max_dy)
        dx = int(dx_f * max_dx)
        img = Image.new("RGBA", (W, H), (0,0,0,0))
        if scale != 1.0:
            sw, sh = int(cw*scale), int(ch*scale)
            scaled = cell.resize((sw,sh), Image.LANCZOS)
            ox, oy = (cw-sw)//2, (ch-sh)//2
            img.paste(scaled, (ox+dx, padding//2+oy+dy), scaled)
        else:
            img.paste(cell, (dx, padding//2+dy), cell)
        return img

    N = 10

    if state == "thinking":
        frames = []
        for i in range(N*2):
            t = i/(N*2)
            dx = math.sin(t*2*math.pi)*0.7
            dy = -abs(math.sin(t*2*math.pi))*0.3
            frames.append((frame(dy, dx), 100))
        return frames

    elif state == "working":
        return [
            (frame(-0.6, 0),  70),
            (frame(0.0,  0),  55),
            (frame(-0.9, 0),  70),
            (frame(0.0,  0),  55),
            (frame(-0.4, 0),  70),
            (frame(0.0,  0), 110),
        ]

    elif state == "error":
        return [
            (frame(0,  0.0),  50),
            (frame(0,  1.0),  55),
            (frame(0, -1.0),  55),
            (frame(0,  1.0),  55),
            (frame(0, -1.0),  55),
            (frame(0,  0.5),  55),
            (frame(0, -0.5),  55),
            (frame(0,  0.0), 280),
        ]

    elif state == "attention":
        seq = []
        for i in range(7):
            t = i/6
            dy = -ease_in_out(math.sin(t*math.pi))
            sc = 1.0 + 0.06*math.sin(t*math.pi)
            seq.append((frame(dy, scale=sc), 65))
        seq += [(frame(0.1), 75), (frame(0.0), 140)]
        return seq

    elif state == "notification":
        return [
            (frame(-1.0), 75),
            (frame(-0.4), 55),
            (frame(0.0),  75),
            (frame(-0.3), 55),
            (frame(0.0), 190),
        ]

    elif state == "sleeping":
        frames = []
        for i in range(N*2):
            t = i/(N*2)
            dy = math.sin(t*2*math.pi)*0.18
            frames.append((frame(dy), 140))
        return frames

    elif state == "waking":
        return [
            (frame(-1.0), 65),
            (frame(-0.5), 55),
            (frame(0.0),  65),
            (frame(-0.4), 55),
            (frame(0.0),  90),
        ]

    else:
        # idle — handled as SVG; this is fallback
        frames = []
        for i in range(N):
            t = i/N
            dy = -ease_in_out(math.sin(t*math.pi))
            frames.append((frame(dy), 80))
        for i in range(N):
            t = i/N
            dy = ease_in_out(math.sin(t*math.pi))*0.25
            frames.append((frame(dy), 80))
        return frames


# ──────────────────────────────────────────────
# APNG builder
# ──────────────────────────────────────────────

def build_apng(frames_with_delays, out_path: Path):
    from apng import APNG, PNG
    tmp = Path(tempfile.mkdtemp())
    try:
        anim = APNG()
        for i, (img, delay) in enumerate(frames_with_delays):
            p = tmp / f"f{i:03d}.png"
            img.convert("RGBA").save(str(p), "PNG")
            anim.append(PNG.from_bytes(p.read_bytes()), delay=delay, delay_den=1000)
        anim.save(str(out_path))
    finally:
        for f in tmp.glob("*.png"): f.unlink()
        tmp.rmdir()
    W, H = frames_with_delays[0][0].size
    print(f"    → {out_path.name}  ({len(frames_with_delays)} frames, {W}×{H})")


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def process(sheet_path: str, output_dir: str):
    sheet = Image.open(sheet_path).convert("RGBA")
    W, H = sheet.size
    cols, rows = 4, 2
    cw, ch = W//cols, H//rows
    PADDING = 50

    out = Path(output_dir)
    assets = out / "assets"
    assets.mkdir(parents=True, exist_ok=True)

    vw, vh = cw, ch + PADDING

    print(f"Sheet: {W}×{H}px  →  cell: {cw}×{ch}px")

    for col, row, state, desc in POSES:
        box = (col*cw, row*ch, (col+1)*cw, (row+1)*ch)
        cell = remove_background(sheet.crop(box))
        print(f"  [{state}]")

        if state == "idle":
            # SVG for eye tracking
            svg_path = assets / "bunny-idle.svg"
            make_idle_svg(cell, svg_path, vw, vh, PADDING)
        else:
            frames = make_frames(cell, state, PADDING)
            build_apng(frames, assets / f"bunny-{state}.apng")

    # ── theme.json ──────────────────────────────
    eye_rx = 0.5   # will be tuned by detect_eyes centroid / vw
    eye_ry = 0.40

    theme = {
        "schemaVersion": 1,
        "name": "Bunny",
        "author": "harim.noh@outta.ai",
        "version": "1.0.0",
        "description": "Dark navy bunny with WB star - eye tracking idle",

        "viewBox": {"x": 0, "y": 0, "width": vw, "height": vh},

        "layout": {
            "contentBox": {"x": int(vw*0.06), "y": PADDING//2, "width": int(vw*0.88), "height": ch},
            "centerX": vw//2,
            "baselineY": vh - 4,
            "visibleHeightRatio": 0.60,
            "baselineBottomRatio": 0.03,
        },

        "eyeTracking": {
            "enabled": True,
            "states": ["idle"],
            "eyeRatioX": eye_rx,
            "eyeRatioY": eye_ry,
            "maxOffset": int(vw * 0.025),
            "bodyScale": 0.15,
            "shadowStretch": 0.08,
            "shadowShift": 0.15,
            "ids": {
                "eyes":   "eyes-js",
                "body":   "body-js",
                "shadow": "shadow-js",
            },
            "shadowOrigin": f"{vw//2}px {vh-4}px",
        },

        "states": {
            "idle":         ["bunny-idle.svg"],
            "thinking":     ["bunny-thinking.apng"],
            "working":      ["bunny-working.apng"],
            "error":        ["bunny-error.apng"],
            "attention":    ["bunny-attention.apng"],
            "notification": ["bunny-notification.apng"],
            "sleeping":     ["bunny-sleeping.apng"],
            "waking":       ["bunny-waking.apng"],
        },

        "sleepSequence": {"mode": "direct"},

        "workingTiers": [
            {"minSessions": 2, "file": "bunny-working.apng"},
            {"minSessions": 1, "file": "bunny-working.apng"},
        ],

        "timings": {
            "mouseIdleTimeout": 25000,
            "mouseSleepTimeout": 90000,
        },

        "hitBoxes": {
            "default":  {"x": int(vw*0.08), "y": PADDING//2 + int(ch*0.15), "w": int(vw*0.84), "h": int(ch*0.82)},
            "sleeping": {"x": int(vw*0.04), "y": PADDING//2 + int(ch*0.40), "w": int(vw*0.92), "h": int(ch*0.55)},
        },
        "sleepingHitboxFiles": ["bunny-sleeping.apng"],

        "reactions": {
            "clickLeft":  {"file": "bunny-attention.apng", "duration": 2000},
            "clickRight": {"file": "bunny-waking.apng",    "duration": 2000},
            "double":     {"files": ["bunny-attention.apng"], "duration": 3000},
        },

        "miniMode": {"supported": False},

        "objectScale": {
            "widthRatio":  2.0,
            "heightRatio": 2.0,
            "offsetX": -0.5,
            "offsetY": -0.5,
        },
    }

    (out / "theme.json").write_text(json.dumps(theme, indent=2, ensure_ascii=True), encoding="utf-8")
    print(f"\ntheme.json written → {out/'theme.json'}")
    return out


def get_install_dir():
    import platform
    s = platform.system()
    if s == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home()/"AppData"/"Roaming"))
        return base / "clawd-on-desk" / "themes" / "bunny"
    elif s == "Darwin":
        return Path.home()/"Library"/"Application Support"/"clawd-on-desk"/"themes"/"bunny"
    else:
        return Path.home()/".config"/"clawd-on-desk"/"themes"/"bunny"


def install(theme_dir: Path):
    dest = get_install_dir()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(theme_dir, dest)
    print(f"\nInstalled → {dest}")
    print("Restart Clawd on Desk → Settings → Theme → Bunny")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 process_sticker_sheet2.py <kitty2.png>")
        sys.exit(1)
    sheet = sys.argv[1]
    outdir = sys.argv[2] if len(sys.argv) > 2 else str(Path(tempfile.gettempdir())/"clawd-bunny-theme")
    print(f"Processing: {sheet}")
    d = process(sheet, outdir)
    install(d)
