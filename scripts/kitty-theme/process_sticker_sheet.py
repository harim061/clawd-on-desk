#!/usr/bin/env python3
"""
Process the 8-pose Clawd kitty sticker sheet into a custom theme.

Usage:
    python3 process_sticker_sheet.py <path-to-image>

Steps:
    1. Split 4x2 grid into 8 individual poses
    2. Remove purple background → transparent PNG
    3. Create APNG animations (gentle float/bounce per state)
    4. Generate theme.json
    5. Install to ~/.config/clawd-on-desk/themes/kitty/
"""

import sys
import os
import math
import json
import shutil
from pathlib import Path
from PIL import Image, ImageFilter
import tempfile
import struct
import zlib

# ──────────────────────────────────────────────
# Pose definitions (4 cols × 2 rows)
# ──────────────────────────────────────────────
POSES = [
    # (col, row, state_name,       description)
    (0, 0, "idle",          "neutral sitting"),
    (1, 0, "thinking",      "question mark look-away"),
    (2, 0, "working",       "typing on laptop"),
    (3, 0, "error",         "nervous sweat drop"),
    (0, 1, "attention",     "sparkles happy"),
    (1, 1, "notification",  "exclamation alert"),
    (2, 1, "sleeping",      "zzz lying down"),
    (3, 1, "waking",        "happy wink"),
]

# Animation frames: (dy_px, scale, duration_ms) per frame
ANIMATIONS = {
    "idle":         [(0, 1.00, 600), (-3, 1.00, 600)],          # gentle float
    "thinking":     [(0, 1.00, 500), (-2, 1.00, 800), (0, 1.00, 500)],
    "working":      [(0, 1.00, 200), (-2, 1.00, 200), (0, 1.00, 200), (-1, 1.00, 200)],  # typing
    "error":        [(0, 1.00, 300), (2, 1.00, 150), (-2, 1.00, 150), (0, 1.00, 600)],  # shake
    "attention":    [(0, 1.00, 400), (-5, 1.00, 300), (0, 1.00, 400)],  # bounce
    "notification": [(0, 1.00, 300), (-3, 1.00, 200), (0, 1.00, 300)],
    "sleeping":     [(0, 1.00, 1000), (-1, 1.00, 1000)],         # slow breathe
    "waking":       [(0, 1.00, 200), (-3, 1.00, 300), (0, 1.00, 300)],
}


# ──────────────────────────────────────────────
# Background removal
# ──────────────────────────────────────────────

def remove_background(img: Image.Image, tol: int = 35) -> Image.Image:
    """Remove the solid purple/lavender background, keeping sticker + shadow."""
    img = img.convert("RGBA")
    pixels = img.load()
    w, h = img.size

    # Sample background colour from a corner
    bg = img.getpixel((5, 5))[:3]

    def dist(c):
        return math.sqrt(sum((a - b) ** 2 for a, b in zip(c[:3], bg)))

    for y in range(h):
        for x in range(w):
            px = pixels[x, y]
            if dist(px) < tol:
                pixels[x, y] = (px[0], px[1], px[2], 0)

    # Light alpha-smoothing on edges
    img = img.filter(ImageFilter.SMOOTH_MORE)
    return img


# ──────────────────────────────────────────────
# APNG builder (pure-Python, no extra deps)
# ──────────────────────────────────────────────

def _make_png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    c = struct.pack(">I", len(data)) + chunk_type + data
    return c + struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)


def _png_idat_data(img: Image.Image) -> bytes:
    """Return raw deflated scanlines for a single frame."""
    raw = bytearray()
    for y in range(img.height):
        raw.append(0)  # filter type = None
        for x in range(img.width):
            r, g, b, a = img.getpixel((x, y))
            raw.extend([r, g, b, a])
    return zlib.compress(bytes(raw))


def build_gif(frames_with_delays, out_path: Path):
    """Save animated GIF with transparency using Pillow."""
    W, H = frames_with_delays[0][0].size
    pil_frames = []
    durations = []
    for frame_img, delay_ms in frames_with_delays:
        rgba = frame_img.convert("RGBA").resize((W, H), Image.LANCZOS)
        # Convert to palette with transparency
        p = Image.new("P", rgba.size)
        p.paste(rgba.convert("RGB"))
        rgba_data = rgba.load()
        # Use GIF transparency: convert RGBA → P with transparent index
        gif_frame = rgba.convert("RGB").quantize(colors=255, method=Image.Quantize.MEDIANCUT)
        pil_frames.append(gif_frame)
        durations.append(delay_ms)

    pil_frames[0].save(
        str(out_path),
        format="GIF",
        save_all=True,
        append_images=pil_frames[1:],
        loop=0,
        duration=durations,
        optimize=False,
    )
    print(f"  → {out_path.name}  ({len(frames_with_delays)} frames, {W}×{H})")


def build_apng(frames_with_delays, out_path: Path):
    """
    frames_with_delays: list of (PIL.Image RGBA, delay_ms int)
    Writes a valid APNG using the apng library.
    """
    from apng import APNG, PNG
    import tempfile, os

    tmp_dir = Path(tempfile.mkdtemp())
    png_paths = []
    delays = []
    W, H = frames_with_delays[0][0].size

    for i, (frame_img, delay_ms) in enumerate(frames_with_delays):
        frame_rgba = frame_img.convert("RGBA").resize((W, H), Image.LANCZOS)
        p = tmp_dir / f"frame_{i:03d}.png"
        frame_rgba.save(str(p), "PNG")
        png_paths.append(str(p))
        delays.append(delay_ms)

    anim = APNG()
    for path, delay_ms in zip(png_paths, delays):
        png = PNG.from_bytes(open(path, "rb").read())
        anim.append(png, delay=delay_ms, delay_den=1000)

    anim.save(str(out_path))

    # cleanup temp frames
    for p in png_paths:
        os.remove(p)
    tmp_dir.rmdir()

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

    for col, row, state, desc in POSES:
        box = (col * cw, row * ch, (col + 1) * cw, (row + 1) * ch)
        cell = sheet.crop(box)
        cell_clean = remove_background(cell)

        # Build animated frames with vertical offset
        anim_def = ANIMATIONS.get(state, [(0, 1.0, 600)])
        canvas_h = ch + 10  # extra padding for bounce headroom
        frames = []
        for dy, _scale, delay_ms in anim_def:
            canvas = Image.new("RGBA", (cw, canvas_h), (0, 0, 0, 0))
            paste_y = max(0, abs(dy))
            canvas.paste(cell_clean, (0, paste_y + dy))
            frames.append((canvas, delay_ms))

        gif_path = assets_dir / f"kitty-{state}.gif"
        build_gif(frames, gif_path)

    # ── theme.json ──────────────────────────────
    theme = {
        "schemaVersion": 1,
        "name": "Kitty",
        "author": "harim.noh@outta.ai",
        "version": "1.0.0",
        "description": "Cute white kitty sticker mascot",

        "viewBox": {"x": 0, "y": 0, "width": cw, "height": ch + 10},

        "layout": {
            "contentBox": {"x": int(cw * 0.05), "y": 5, "width": int(cw * 0.90), "height": ch},
            "centerX": cw // 2,
            "baselineY": ch + 5,
            "visibleHeightRatio": 0.38,
            "baselineBottomRatio": 0.04
        },

        "eyeTracking": {"enabled": False},

        "states": {
            "idle":         [f"kitty-idle.gif"],
            "thinking":     [f"kitty-thinking.gif"],
            "working":      [f"kitty-working.gif"],
            "error":        [f"kitty-error.gif"],
            "attention":    [f"kitty-attention.gif"],
            "notification": [f"kitty-notification.gif"],
            "sleeping":     [f"kitty-sleeping.gif"],
            "waking":       [f"kitty-waking.gif"],
        },

        "sleepSequence": {"mode": "direct"},

        "workingTiers": [
            {"minSessions": 2, "file": "kitty-working.gif"},
            {"minSessions": 1, "file": "kitty-working.gif"},
        ],

        "timings": {
            "mouseIdleTimeout": 25000,
            "mouseSleepTimeout": 90000
        },

        "hitBoxes": {
            "default":  {"x": int(cw * 0.1), "y": int(ch * 0.3), "w": int(cw * 0.8), "h": int(ch * 0.65)},
            "sleeping": {"x": int(cw * 0.05), "y": int(ch * 0.5), "w": int(cw * 0.9), "h": int(ch * 0.45)},
        },
        "sleepingHitboxFiles": ["kitty-sleeping.gif"],

        "reactions": {
            "clickLeft":  {"file": "kitty-attention.gif", "duration": 2000},
            "clickRight": {"file": "kitty-waking.gif",    "duration": 2000},
            "double":     {"files": ["kitty-attention.gif"], "duration": 3000},
        },

        "miniMode": {"supported": False},

        "objectScale": {
            "widthRatio": 1.0,
            "heightRatio": 1.0,
            "offsetX": 0.0,
            "offsetY": 0.0,
        }
    }

    theme_json_path = out / "theme.json"
    theme_json_path.write_text(json.dumps(theme, indent=2, ensure_ascii=False))
    print(f"\ntheme.json written → {theme_json_path}")

    return out


def get_theme_install_dir() -> Path:
    """Return platform-appropriate user theme directory."""
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

    import tempfile
    sheet_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else str(Path(tempfile.gettempdir()) / "clawd-kitty-theme")

    print(f"Processing: {sheet_path}")
    theme_dir = process(sheet_path, output_dir)
    install_theme(theme_dir)
