#!/usr/bin/env python3
"""
Generate AppIcon.appiconset + MenuBarIcon.imageset for PageFly Capture.

Design: rounded-square indigo gradient with a centered white ring + a small
offset dot. Evokes "capture point / focus" and reads cleanly down to 16px.

The menu bar imageset is a template (black glyph on transparent), so AppKit
can tint it via button.contentTintColor from MenuBarController.
"""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter
import json

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "Resources" / "Assets.xcassets"
APP_ICONSET = ASSETS / "AppIcon.appiconset"
MENUBAR_IMAGESET = ASSETS / "MenuBarIcon.imageset"


# ── App icon ────────────────────────────────────────────────────────────

APP_SIZES = [
    # (canvas px, variant id, size pt, scale)
    (16,  "16x16@1x",   16, 1),
    (32,  "16x16@2x",   16, 2),
    (32,  "32x32@1x",   32, 1),
    (64,  "32x32@2x",   32, 2),
    (128, "128x128@1x", 128, 1),
    (256, "128x128@2x", 128, 2),
    (256, "256x256@1x", 256, 1),
    (512, "256x256@2x", 256, 2),
    (512, "512x512@1x", 512, 1),
    (1024,"512x512@2x", 512, 2),
]

TOP_COLOR = (99, 102, 241)        # indigo-500
BOTTOM_COLOR = (49, 46, 129)      # indigo-900
DOT_COLOR = (255, 255, 255)
RING_ALPHA = 235


def rounded_rect_mask(size: int, radius_ratio: float = 0.225) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(mask)
    r = int(size * radius_ratio)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=255)
    return mask


def draw_app_icon(size: int) -> Image.Image:
    """Single 1024-style render scaled down to `size`."""
    # Work at 2x for anti-aliasing, then resize down.
    s = size * 4
    canvas = Image.new("RGBA", (s, s), (0, 0, 0, 0))

    # Vertical gradient background.
    bg = Image.new("RGBA", (s, s))
    for y in range(s):
        t = y / (s - 1)
        r = int(TOP_COLOR[0] * (1 - t) + BOTTOM_COLOR[0] * t)
        g = int(TOP_COLOR[1] * (1 - t) + BOTTOM_COLOR[1] * t)
        b = int(TOP_COLOR[2] * (1 - t) + BOTTOM_COLOR[2] * t)
        ImageDraw.Draw(bg).line([(0, y), (s, y)], fill=(r, g, b, 255))

    mask = rounded_rect_mask(s)
    canvas.paste(bg, (0, 0), mask)

    d = ImageDraw.Draw(canvas, "RGBA")

    # Outer ring — hairline, slightly off-center for focus-point feel.
    cx, cy = s / 2, s / 2
    outer_r = s * 0.30
    ring_width = max(2, int(s * 0.022))
    d.ellipse(
        [cx - outer_r, cy - outer_r, cx + outer_r, cy + outer_r],
        outline=(255, 255, 255, RING_ALPHA),
        width=ring_width,
    )

    # Inner dot — the "capture" point.
    inner_r = s * 0.095
    d.ellipse(
        [cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r],
        fill=(255, 255, 255, 255),
    )

    # Small satellite dot top-right to telegraph "capture / record".
    sat_cx, sat_cy = cx + s * 0.24, cy - s * 0.24
    sat_r = s * 0.035
    d.ellipse(
        [sat_cx - sat_r, sat_cy - sat_r, sat_cx + sat_r, sat_cy + sat_r],
        fill=(255, 255, 255, 255),
    )

    # Subtle top highlight band for depth.
    highlight = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    hd = ImageDraw.Draw(highlight)
    hd.ellipse([s * 0.08, -s * 0.6, s * 0.92, s * 0.3], fill=(255, 255, 255, 40))
    highlight = highlight.filter(ImageFilter.GaussianBlur(radius=s * 0.02))
    canvas = Image.alpha_composite(canvas, Image.composite(
        highlight, Image.new("RGBA", (s, s), (0, 0, 0, 0)), mask))

    # Resize to target with a high-quality filter.
    return canvas.resize((size, size), Image.LANCZOS)


def write_app_iconset():
    APP_ICONSET.mkdir(parents=True, exist_ok=True)
    images = []
    for (px, variant, pt, scale) in APP_SIZES:
        filename = f"icon-{variant}.png"
        draw_app_icon(px).save(APP_ICONSET / filename, "PNG")
        images.append({
            "filename": filename,
            "idiom": "mac",
            "scale": f"{scale}x",
            "size": f"{pt}x{pt}",
        })
    contents = {"images": images, "info": {"author": "xcode", "version": 1}}
    (APP_ICONSET / "Contents.json").write_text(json.dumps(contents, indent=2))


# ── Menu bar icon ───────────────────────────────────────────────────────

def draw_menubar_icon(size: int) -> Image.Image:
    """Template glyph — black silhouette on transparent, AppKit tints it.

    Design: a "captured page" — rounded document silhouette with a folded
    top-right corner and a few text-line cutouts. Reads clearly at 18pt
    and doesn't resemble the standard record-button glyph.
    """
    s = size * 8  # supersample heavily for anti-aliasing
    mask = Image.new("L", (s, s), 0)  # alpha-only mask we'll fill + punch
    d = ImageDraw.Draw(mask)

    # Page shape: pentagon with a chamfered top-right corner ("fold").
    page = [
        (int(s * 0.18), int(s * 0.13)),   # top-left
        (int(s * 0.64), int(s * 0.13)),   # top edge before the fold
        (int(s * 0.82), int(s * 0.31)),   # corner of fold
        (int(s * 0.82), int(s * 0.87)),   # bottom-right
        (int(s * 0.18), int(s * 0.87)),   # bottom-left
    ]
    d.polygon(page, fill=255)

    # Fold indicator — a small triangle cut out so the folded corner reads
    # like a dog-ear rather than a chamfer.
    fold = [
        (int(s * 0.64), int(s * 0.13)),
        (int(s * 0.64), int(s * 0.31)),
        (int(s * 0.82), int(s * 0.31)),
    ]
    d.polygon(fold, fill=0)

    # Three "text lines" punched through the page.
    line_h = int(s * 0.07)
    lines = [
        (int(s * 0.28), int(s * 0.52), int(s * 0.73), int(s * 0.52) + line_h),
        (int(s * 0.28), int(s * 0.65), int(s * 0.66), int(s * 0.65) + line_h),
        (int(s * 0.28), int(s * 0.78), int(s * 0.73), int(s * 0.78) + line_h),
    ]
    for rect in lines:
        d.rectangle(rect, fill=0)

    # Compose: black ink masked by the alpha we just built.
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ink = Image.new("RGBA", (s, s), (0, 0, 0, 255))
    img.paste(ink, (0, 0), mask)

    return img.resize((size, size), Image.LANCZOS)


def write_menubar_imageset():
    MENUBAR_IMAGESET.mkdir(parents=True, exist_ok=True)
    draw_menubar_icon(18).save(MENUBAR_IMAGESET / "menubar-18.png", "PNG")
    draw_menubar_icon(36).save(MENUBAR_IMAGESET / "menubar-36.png", "PNG")
    contents = {
        "images": [
            {"filename": "menubar-18.png", "idiom": "mac", "scale": "1x"},
            {"filename": "menubar-36.png", "idiom": "mac", "scale": "2x"},
        ],
        "info": {"author": "xcode", "version": 1},
        "properties": {"template-rendering-intent": "template"},
    }
    (MENUBAR_IMAGESET / "Contents.json").write_text(json.dumps(contents, indent=2))


# ── xcassets wrapper ────────────────────────────────────────────────────

def write_xcassets_contents():
    (ASSETS / "Contents.json").write_text(json.dumps(
        {"info": {"author": "xcode", "version": 1}}, indent=2
    ))


if __name__ == "__main__":
    write_xcassets_contents()
    write_app_iconset()
    write_menubar_imageset()
    print(f"wrote app icons → {APP_ICONSET}")
    print(f"wrote menu bar icon → {MENUBAR_IMAGESET}")
