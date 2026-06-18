#!/usr/bin/env python3
"""
Process the 8-pose Clawd kitty sticker sheet into a custom theme.

Usage:
    python3 process_sticker_sheet.py <path-to-image>
"""

import sys
import os
import math
import json
import shutil
import tempfile
from pathlib import Path
from PIL import Image, ImageFilter

# ──────────────────────────────────────────────
# Pose definitions (4 cols × 2 rows)
# ──────────────────────────────────────────────
POSES = [
    (0, 0, "idle",          "neutral sitting"),
    (1, 0, "thinking",      "question mark look-away"),
    (2, 0, "working",       "typing on laptop"),
    (3, 0, "error",         "nervous sweat drop"),
    (0, 1, "attention",     "sparkles happy"),
    (1, 1, "notification",  "exclamation alert"),
    (2, 1, "sleeping",      "zzz lying down"),
    (3, 1, "waking",        "happy wink"),
]


def ease_in_out(t):
    return t * t * (3 - 2 * t)


def make_frames(cell: Image.Image, state: str):
    """
    Generate (PIL.Image, delay_ms) frame list for each state.
    Uses smooth sine/easing interpolation for natural motion.
    """
    cw, ch = cell.size
    PADDING = 40  # extra canvas space for movement

    def canvas(dy_frac, dx_frac=0.0, scale=1.0):
        """Paste cell onto a larger canvas with given offsets."""
        max_dy = int(ch * 0.07)   # 7% of height
        max_dx = int(cw * 0.04)
        dy = int(dy_frac * max_dy)
        dx = int(dx_frac * max_dx)
        W, H = cw, ch + PADDING
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        if scale != 1.0:
            sw = int(cw * scale)
            sh = int(ch * scale)
            scaled = cell.resize((sw, sh), Image.LANCZOS)
            ox = (cw - sw) // 2
            oy = (ch - sh) // 2
            img.paste(scaled, (ox + dx, PADDING // 2 + oy + dy), scaled)
        else:
            img.paste(cell, (dx, PADDING // 2 + dy), cell)
        return img

    # Build per-state keyframe sequences
    # Each entry: (dy_fraction, dx_fraction, scale, delay_ms)
    # dy: -1=up, +1=down | smooth float uses sine curve
    N = 8  # frames per cycle for smooth animation

    if state == "idle":
        # Gentle float up and down (sine wave)
        frames = []
        for i in range(N):
            t = i / N
            dy = -ease_in_out(math.sin(t * math.pi))  # 0 → up → 0
            frames.append((canvas(dy), 80))
        for i in range(N):
            t = i / N
            dy = ease_in_out(math.sin(t * math.pi)) * 0.3  # 0 → slight down → 0
            frames.append((canvas(dy), 80))
        return frames

    elif state == "thinking":
        # Slow sway left-right
        frames = []
        for i in range(N * 2):
            t = i / (N * 2)
            dx = math.sin(t * 2 * math.pi) * 0.6
            dy = -abs(math.sin(t * 2 * math.pi)) * 0.3
            frames.append((canvas(dy, dx), 100))
        return frames

    elif state == "working":
        # Quick typing bounce (fast up-down)
        seq = [
            (canvas(-0.5, 0),  80),
            (canvas(0.0,  0),  60),
            (canvas(-0.8, 0),  80),
            (canvas(0.0,  0),  60),
            (canvas(-0.3, 0),  80),
            (canvas(0.0,  0), 120),
        ]
        return seq

    elif state == "error":
        # Shake left-right
        seq = [
            (canvas(0,  0.0),  60),
            (canvas(0,  1.0),  60),
            (canvas(0, -1.0),  60),
            (canvas(0,  1.0),  60),
            (canvas(0, -1.0),  60),
            (canvas(0,  0.5),  60),
            (canvas(0, -0.5),  60),
            (canvas(0,  0.0), 300),
        ]
        return seq

    elif state == "attention":
        # Big happy bounce
        seq = []
        for i in range(6):
            t = i / 5
            dy = -ease_in_out(math.sin(t * math.pi))
            scale = 1.0 + 0.05 * math.sin(t * math.pi)
            seq.append((canvas(dy, scale=scale), 70))
        seq.append((canvas(0.1), 80))
        seq.append((canvas(0.0), 150))
        return seq

    elif state == "notification":
        # Pop up then settle
        seq = [
            (canvas(-1.0), 80),
            (canvas(-0.5), 60),
            (canvas(0.0),  80),
            (canvas(-0.3), 60),
            (canvas(0.0), 200),
        ]
        return seq

    elif state == "sleeping":
        # Very slow breathe
        frames = []
        for i in range(N * 2):
            t = i / (N * 2)
            dy = math.sin(t * 2 * math.pi) * 0.2
            frames.append((canvas(dy), 150))
        return frames

    elif state == "waking":
        # Quick bounce + settle
        seq = [
            (canvas(-1.0), 70),
            (canvas(-0.5), 60),
            (canvas(0.0),  70),
            (canvas(-0.4), 60),
            (canvas(0.0), 100),
        ]
        return seq

    else:
        return [(canvas(0), 500)]


# ──────────────────────────────────────────────
# Background removal
# ──────────────────────────────────────────────

def remove_background(img: Image.Image, tol: int = 40) -> Image.Image:
    """Remove solid purple/lavender background → transparent."""
    img = img.convert("RGBA")
    pixels = img.load()
    w, h = img.size

    # Sample from multiple corners for robustness
    corners = [(5, 5), (w - 5, 5), (5, h - 5), (w - 5, h - 5)]
    bg_samples = [img.getpixel(c)[:3] for c in corners]
    # Pick most common-ish (just average them)
    bg = tuple(int(sum(c[i] for c in bg_samples) / len(bg_samples)) for i in range(3))

    def dist(c):
        return math.sqrt(sum((a - b) ** 2 for a, b in zip(c[:3], bg)))

    for y in range(h):
        for x in range(w):
            px = pixels[x, y]
            d = dist(px)
            if d < tol:
                pixels[x, y] = (px[0], px[1], px[2], 0)
            elif d < tol * 1.5:
                # soft edge fade
                alpha = int(255 * (d - tol) / (tol * 0.5))
                pixels[x, y] = (px[0], px[1], px[2], min(alpha, px[3]))

    return img


# ──────────────────────────────────────────────
# APNG builder using apng library
# ──────────────────────────────────────────────

def build_apng(frames_with_delays, out_path: Path):
    from apng import APNG, PNG

    tmp_dir = Path(tempfile.mkdtemp())
    try:
        anim = APNG()
        for i, (frame_img, delay_ms) in enumerate(frames_with_delays):
            p = tmp_dir / f"f{i:03d}.png"
            frame_img.convert("RGBA").save(str(p), "PNG")
            png = PNG.from_bytes(p.read_bytes())
            anim.append(png, delay=delay_ms, delay_den=1000)
        anim.save(str(out_path))
    finally:
        for f in tmp_dir.glob("*.png"):
            f.unlink()
        tmp_dir.rmdir()

    W, H = frames_with_delays[0][0].size
    print(f"  → {out_path.name}  ({len(frames_with_delays)} frames, {W}×{H})")


# ──────────────────────────────────────────────
# Main processing
# ──────────────────────────────────────────────

def process(sheet_path: str, output_dir: str):
    sheet = Image.open(sheet_path).convert("RGBA")
    W, H = sheet.size
    cols, rows = 4, 2
    cw, ch = W // cols, H // rows

    out = Path(output_dir)
    assets_dir = out / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    print(f"Sheet: {W}×{H}px  →  cell: {cw}×{ch}px")

    PADDING = 40
    canvas_h = ch + PADDING

    for col, row, state, desc in POSES:
        box = (col * cw, row * ch, (col + 1) * cw, (row + 1) * ch)
        cell = sheet.crop(box)
        cell_clean = remove_background(cell)

        frames = make_frames(cell_clean, state)
        apng_path = assets_dir / f"kitty-{state}.apng"
        build_apng(frames, apng_path)

    # ── theme.json ──────────────────────────────
    theme = {
        "schemaVersion": 1,
        "name": "Kitty",
        "author": "harim.noh@outta.ai",
        "version": "1.0.0",
        "description": "Cute white kitty sticker mascot",

        "viewBox": {"x": 0, "y": 0, "width": cw, "height": canvas_h},

        "layout": {
            "contentBox": {"x": int(cw * 0.05), "y": PADDING // 2, "width": int(cw * 0.90), "height": ch},
            "centerX": cw // 2,
            "baselineY": canvas_h - 5,
            "visibleHeightRatio": 0.38,
            "baselineBottomRatio": 0.04,
        },

        "eyeTracking": {"enabled": False},

        "states": {
            "idle":         ["kitty-idle.apng"],
            "thinking":     ["kitty-thinking.apng"],
            "working":      ["kitty-working.apng"],
            "error":        ["kitty-error.apng"],
            "attention":    ["kitty-attention.apng"],
            "notification": ["kitty-notification.apng"],
            "sleeping":     ["kitty-sleeping.apng"],
            "waking":       ["kitty-waking.apng"],
        },

        "sleepSequence": {"mode": "direct"},

        "workingTiers": [
            {"minSessions": 2, "file": "kitty-working.apng"},
            {"minSessions": 1, "file": "kitty-working.apng"},
        ],

        "timings": {
            "mouseIdleTimeout": 25000,
            "mouseSleepTimeout": 90000,
        },

        "hitBoxes": {
            "default":  {"x": int(cw * 0.1), "y": PADDING // 2 + int(ch * 0.2), "w": int(cw * 0.8), "h": int(ch * 0.75)},
            "sleeping": {"x": int(cw * 0.05), "y": PADDING // 2 + int(ch * 0.4), "w": int(cw * 0.9), "h": int(ch * 0.55)},
        },
        "sleepingHitboxFiles": ["kitty-sleeping.apng"],

        "reactions": {
            "clickLeft":  {"file": "kitty-attention.apng", "duration": 2000},
            "clickRight": {"file": "kitty-waking.apng",    "duration": 2000},
            "double":     {"files": ["kitty-attention.apng"], "duration": 3000},
        },

        "miniMode": {"supported": False},

        "objectScale": {
            "widthRatio": 1.0,
            "heightRatio": 1.0,
            "offsetX": 0.0,
            "offsetY": 0.0,
        },
    }

    theme_json_path = out / "theme.json"
    theme_json_path.write_text(json.dumps(theme, indent=2, ensure_ascii=False))
    print(f"\ntheme.json written → {theme_json_path}")
    return out


def get_theme_install_dir() -> Path:
    import platform
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / "clawd-on-desk" / "themes" / "kitty"
    elif system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "clawd-on-desk" / "themes" / "kitty"
    else:
        return Path.home() / ".config" / "clawd-on-desk" / "themes" / "kitty"


def install_theme(theme_dir: Path):
    dest = get_theme_install_dir()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(theme_dir, dest)
    print(f"\nInstalled → {dest}")
    print("Restart Clawd on Desk and select 'Kitty' theme in settings!")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 process_sticker_sheet.py <sticker-sheet.png>")
        sys.exit(1)

    sheet_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else str(Path(tempfile.gettempdir()) / "clawd-kitty-theme")

    print(f"Processing: {sheet_path}")
    theme_dir = process(sheet_path, output_dir)
    install_theme(theme_dir)
