#!/usr/bin/env python3
"""
Makes the Pinterest pin image for an outfit campaign: the campaign's
outfit-preview photo with a price overlay, saved as outfit-pin.jpg next
to it. Replaces the manual Gemini overlay.

Usage:
    python make_outfit_pin.py outfits/casual/casual-outfit-oct-12
    python make_outfit_pin.py --batch oct-12   (every campaign dated oct-12,
                                                 incl. -oct-12-2, -oct-12-3 ...)
    python make_outfit_pin.py --all            (every campaign in outfits/)
    python make_outfit_pin.py --style band ...  (one of the other styles)

Styles (default fade):
    fade     price text centred in a fade at the bottom, as large as fits
             (price line up to 70% of the width): a letter-spaced "SHOP THE
             LOOK" (gold "ON SALE NOW" if any item has a discount_percent)
             at half the height of "UNDER $X!" below it (price in gold).
             A photo taller than 3:4 with at least 18% empty floor at the
             bottom keeps its shape; the text goes in a fade over that floor.
             Anything else becomes a 1000x1500 (2:3) pin: the photo shrunk so
             330px of new space opens below it, centred, its sides and bottom
             blending into a deep colour sampled from the bottom of the photo.
    classic  full-width black band at 55% across 68-81% of the height,
             centred white text with a soft drop shadow (the old Gemini look)
    tag      small rounded gold price badge in the emptier top corner
    band     thinner band in a colour sampled from the photo, placed in
             whichever top or bottom zone is least busy

"Busy" is edge density, weighted toward the middle columns where the
outfit usually is. Nothing else about the photo changes, and the
original outfit-preview.* is never written to. The site keeps using the
plain outfit-preview; outfit-pin.jpg is only for Pinterest.

Price: the outfit's products.json prices (every record whose detail page
sits under the campaign folder) are totalled and rounded up to the next
$5, giving "UNDER $X!" (112.30 -> UNDER $115!). An exact multiple of $5
goes up to the next one (115.00 -> UNDER $120!) so the claim stays true.
If any item has no stored price (Amazon, Awin) the total would be
wrong, so fade reads "SHOP THE LOOK" / "FULL FIT ↓" instead
(the other styles say "SHOP THE FULL LOOK").

Font: Anton (assets/fonts/, SIL Open Font License, see Anton-OFL.txt).
"""

import argparse
import colorsys
import glob
import json
import math
import os
import re
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

REPO = os.path.dirname(os.path.abspath(__file__))
PRODUCTS_JSON = os.path.join(REPO, "products.json")
FONT_PATH = os.path.join(REPO, "assets", "fonts", "Anton-Regular.ttf")
PREVIEW_EXTS = (".jpg", ".jpeg", ".png", ".webp")
PIN_NAME = "outfit-pin.jpg"
FALLBACK_TEXT = "SHOP THE FULL LOOK"
GOLD = (0xD4, 0xA0, 0x17)
WHITE = (255, 255, 255)
PIN_W, PIN_H = 1000, 1500    # fade: extended pins are 2:3, Pinterest's standard
SPACE = 330                   # fade: new space opened below the photo (px)
FADE = 0.08                   # fade: photo-to-backdrop blend, fraction of PIN_H
SIDE_BLEND = 0.06             # fade: soft side edges, fraction of the photo width
TEXT_WIDTH = 0.70             # fade: widest the price line may get
TALL = 1.34                   # fade: height/width above this (taller than 3:4) may overlay
MIN_CALM = 0.18               # fade: calm floor needed at the bottom to overlay
CALM_EDGE = 20                # fade: busiest patch a "calm" row may have (0-255 edges)


# ---------------------------------------------------------------- prices

def find_preview(campaign_dir):
    for ext in PREVIEW_EXTS:
        path = os.path.join(campaign_dir, "outfit-preview" + ext)
        if os.path.exists(path):
            return path
    return None


def campaign_products(campaign_dir, products):
    rel = os.path.relpath(campaign_dir, REPO).replace(os.sep, "/").rstrip("/") + "/"
    return [p for p in products if (p.get("detail_page_url") or "").startswith(rel)]


def price_cap(items):
    """Dollar figure for "UNDER $X", or None when a price is missing."""
    if any(p.get("price") is None for p in items):
        return None
    if len({p.get("currency") for p in items}) > 1:
        return None
    cents = sum(round(p["price"] * 100) for p in items)
    return (cents // 500 + 1) * 5


# ---------------------------------------------------------------- helpers

def font_for_cap(cap_px):
    """Anton at the size whose capital letters are cap_px tall."""
    probe = ImageFont.truetype(FONT_PATH, 100).getbbox("H")
    return ImageFont.truetype(FONT_PATH, max(1, round(100 * cap_px / (probe[3] - probe[1]))))


def fit(font, text, max_w, tracking=0):
    w = text_width(font, text, tracking)
    if w <= max_w:
        return font
    return ImageFont.truetype(FONT_PATH, int(font.size * max_w / w))


def text_width(font, text, tracking=0):
    # Per character, matching how _runs draws (one glyph at a time, so no
    # kerning); measuring the whole string would come out narrower.
    return sum(font.getlength(ch) for ch in text) + tracking * max(len(text) - 1, 0)


def cap_top(font):
    return font.getbbox("H")[1]


def cap_h(font):
    b = font.getbbox("H")
    return b[3] - b[1]


def draw_runs(img, x, cap_y, runs, font, tracking=0, shadow=True):
    """Draw [(text, colour), ...] left to right starting at x, with the
    tops of the capitals at cap_y. Optional soft drop shadow."""
    h = img.size[1]
    y = cap_y - cap_top(font)
    if shadow:
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        _runs(ImageDraw.Draw(layer), x + 0.004 * h, y + 0.004 * h, runs, font, tracking, (0, 0, 0, 150))
        img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(0.006 * h)))
    _runs(ImageDraw.Draw(img), x, y, runs, font, tracking, None)


def _runs(draw, x, y, runs, font, tracking, override):
    for text, colour in runs:
        for ch in text:
            draw.text((x, y), ch, font=font, fill=override or colour + (255,))
            x += font.getlength(ch) + tracking


def edge_map(img):
    """Edge strength at ~300px wide, weighted toward the middle columns."""
    small = img.convert("L").resize((300, max(1, round(300 * img.size[1] / img.size[0]))))
    edges = small.filter(ImageFilter.FIND_EDGES).filter(ImageFilter.BoxBlur(2))
    weights = [0.35 + math.exp(-((x - 150) / 70) ** 2) for x in range(300)]
    return edges, weights


def busyness(edge_info, box, img_size):
    """Mean weighted edge strength inside box (full-size pixel coords)."""
    edges, weights = edge_info
    sx = edges.size[0] / img_size[0]
    sy = edges.size[1] / img_size[1]
    x0, y0, x1, y1 = (round(box[0] * sx), round(box[1] * sy),
                      max(round(box[2] * sx), round(box[0] * sx) + 1),
                      max(round(box[3] * sy), round(box[1] * sy) + 1))
    px = edges.load()
    total = wsum = 0
    for yy in range(y0, min(y1, edges.size[1])):
        for xx in range(x0, min(x1, edges.size[0])):
            total += px[xx, yy] * weights[xx]
            wsum += weights[xx]
    return total / wsum if wsum else 0


def deep_colour(img, box, value=0.18):
    """Dominant colour of a region, darkened to a deep tone with its hue kept."""
    region = img.crop(box).convert("RGB")
    region.thumbnail((120, 120))
    q = region.quantize(colors=5)
    counts = sorted(q.getcolors(), reverse=True)
    pal = q.getpalette()
    # Skip near-grey clusters when a coloured one is reasonably common, so
    # the tint carries some of the photo's character.
    best = None
    for count, idx in counts:
        r, g, b = pal[idx * 3: idx * 3 + 3]
        s = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)[1]
        if best is None:
            best = (r, g, b)
        if s > 0.15 and count >= counts[0][0] * 0.4:
            best = (r, g, b)
            break
    hh, s, _ = colorsys.rgb_to_hsv(*(c / 255 for c in best))
    r, g, b = colorsys.hsv_to_rgb(hh, min(s * 1.2, 0.65), value)
    return round(r * 255), round(g * 255), round(b * 255)


# ---------------------------------------------------------------- styles

def style_classic(img, cap, on_sale):
    w, h = img.size
    text = f"UNDER ${cap}!" if cap else FALLBACK_TEXT
    top, bottom = round(0.678 * h), round(0.811 * h)
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(overlay).rectangle([0, top, w, bottom], fill=(0, 0, 0, 140))
    img.alpha_composite(overlay)
    font = fit(font_for_cap(0.064 * h), text, 0.90 * w)
    draw_runs(img, (w - text_width(font, text)) / 2, (top + bottom) / 2 - cap_h(font) / 2,
              [(text, WHITE)], font)


def calm_bottom(img):
    """Fraction of the photo's height, measured up from the bottom, that's
    empty floor: every 2% band in it has no 1/12-width patch with more
    than CALM_EDGE edge strength. A shoe in a band makes it busy (on
    sept-9: pavement 10-17, shoes 51). The one-pixel border is skipped,
    since edge filters always fire there."""
    small = img.convert("L").resize((240, max(2, round(240 * img.size[1] / img.size[0]))))
    edges = small.filter(ImageFilter.FIND_EDGES).crop((1, 1, 239, small.size[1] - 1))
    w, h = edges.size
    px = edges.load()
    calm = 0
    for band in range(50):
        y1, y0 = round(h * (1 - band / 50)), round(h * (1 - (band + 1) / 50))
        for b in range(12):
            xs = range(b * w // 12, (b + 1) * w // 12)
            vals = [px[x, y] for y in range(y0, y1) for x in xs]
            if vals and sum(vals) / len(vals) > CALM_EDGE:
                return calm
        calm = (band + 1) / 50
    return calm


def fade_text(pin, top, bottom, cap, on_sale):
    """Centre the two text lines between top and bottom, as large as fits."""
    if cap is None:
        top_run, big_runs = ("SHOP THE LOOK", WHITE), [("FULL FIT ↓", WHITE)]
    else:
        top_run = ("ON SALE NOW", GOLD) if on_sale else ("SHOP THE LOOK", WHITE)
        big_runs = [("UNDER ", WHITE), (f"${cap}!", GOLD)]
    big_text = "".join(t for t, _ in big_runs)
    w = pin.size[0]

    def block(big):
        small = font_for_cap(0.5 * cap_h(big))
        track = 0.3 * cap_h(small)
        # A short price line ("FULL FIT") can leave the spaced-out top line
        # wider than it; hold that to TEXT_WIDTH too.
        while text_width(small, top_run[0], track) > TEXT_WIDTH * w and small.size > 8:
            small = ImageFont.truetype(FONT_PATH, small.size - 1)
            track = 0.3 * cap_h(small)
        gap = 0.6 * cap_h(small)
        return small, track, gap, cap_h(small) + gap + cap_h(big)

    # The price line up to TEXT_WIDTH of the pin, then smaller until the
    # two-line block fits the height available.
    big = fit(font_for_cap(pin.size[1]), big_text, TEXT_WIDTH * w)
    small, track, gap, bh = block(big)
    while bh > bottom - top and big.size > 8:
        big = ImageFont.truetype(FONT_PATH, big.size - 2)
        small, track, gap, bh = block(big)

    y = top + (bottom - top - bh) / 2
    draw_runs(pin, (w - text_width(small, top_run[0], track)) / 2, y, [top_run], small, track)
    draw_runs(pin, (w - text_width(big, big_text)) / 2, y + cap_h(small) + gap, big_runs, big)


def vertical_fade(pin, y0, y1, colour, max_alpha=255):
    """Rows y0..y1 go from clear to max_alpha of colour (smoothstep)."""
    overlay = Image.new("RGBA", pin.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    for y in range(y0, y1):
        t = (y - y0 + 1) / (y1 - y0)
        d.line([(0, y), (pin.size[0], y)], fill=colour + (round(max_alpha * t * t * (3 - 2 * t)),))
    pin.alpha_composite(overlay)


def style_fade(img, cap, on_sale):
    """Two paths. A photo taller than 3:4 with enough empty floor keeps its
    size and shape and gets the text in a fade over that floor. Anything
    else becomes a PIN_W x PIN_H pin: the photo shrunk to leave SPACE below
    it, centred, fading into a backdrop that holds the text."""
    w, h = img.size
    if h / w > TALL:
        calm = calm_bottom(img)
        if calm >= MIN_CALM:
            return fade_overlay(img, cap, on_sale, calm), "overlay"
    return fade_extend(img, cap, on_sale), "shrink"


def fade_overlay(img, cap, on_sale, calm):
    w, h = img.size
    pin = img.resize((PIN_W, round(h * PIN_W / w)), Image.LANCZOS)
    pw, ph = pin.size
    floor_top = round(ph * (1 - calm))
    colour = deep_colour(pin, (0, floor_top, pw, ph))
    # Fade from a little above the floor, ending at 85% so the floor
    # still reads as floor, not as a pasted bar.
    vertical_fade(pin, max(0, floor_top - round(0.06 * ph)), ph, colour, max_alpha=round(255 * 0.85))
    fade_text(pin, floor_top + 0.1 * (ph - floor_top), ph - 0.04 * ph, cap, on_sale)
    return pin


def fade_extend(img, cap, on_sale):
    w, h = img.size
    scale = min(PIN_W / w, (PIN_H - SPACE) / h)
    pw, ph = round(w * scale), round(h * scale)
    photo = img.resize((pw, ph), Image.LANCZOS)
    colour = deep_colour(photo, (0, round(ph * 0.9), pw, ph))
    x0 = (PIN_W - pw) // 2

    pin = Image.new("RGBA", (PIN_W, PIN_H), colour + (255,))
    pin.alpha_composite(photo, (x0, 0))
    # Soften the photo's side edges into the backdrop strips beside it.
    if pw < PIN_W:
        edge = round(SIDE_BLEND * pw)
        overlay = Image.new("RGBA", pin.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)
        for i in range(edge):
            t = 1 - (i + 1) / (edge + 1)
            a = round(255 * t * t * (3 - 2 * t))
            d.line([(x0 + i, 0), (x0 + i, ph)], fill=colour + (a,))
            d.line([(x0 + pw - 1 - i, 0), (x0 + pw - 1 - i, ph)], fill=colour + (a,))
        pin.alpha_composite(overlay)
    # Fade the bottom of the photo into the backdrop, reaching full
    # strength exactly at the photo's lower edge so there's no seam.
    vertical_fade(pin, ph - min(round(FADE * PIN_H), ph), ph, colour)
    fade_text(pin, ph - 0.3 * FADE * PIN_H, PIN_H - 0.045 * PIN_H, cap, on_sale)
    return pin


def style_tag(img, cap, on_sale):
    w, h = img.size
    text = f"UNDER ${cap}" if cap else FALLBACK_TEXT
    font = font_for_cap(0.032 * h)
    pad_x, pad_y = 0.9 * cap_h(font), 0.65 * cap_h(font)
    bw = text_width(font, text, 0.04 * cap_h(font)) + 2 * pad_x
    bh = cap_h(font) + 2 * pad_y
    margin = 0.045 * w
    edges = edge_map(img)
    corners = {
        "left": (margin, margin),
        "right": (w - margin - bw, margin),
    }
    # Judge each corner on a zone a bit larger than the badge itself.
    def score(pos):
        x, y = pos
        return busyness(edges, (x - margin / 2, y - margin / 2, x + bw + margin / 2, y + bh + margin / 2), (w, h))
    x, y = min(corners.values(), key=score)

    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    off = 0.004 * h
    ImageDraw.Draw(shadow).rounded_rectangle([x + off, y + off, x + bw + off, y + bh + off],
                                             radius=bh * 0.3, fill=(0, 0, 0, 110))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(0.006 * h)))
    ImageDraw.Draw(img).rounded_rectangle([x, y, x + bw, y + bh], radius=bh * 0.3, fill=GOLD + (255,))
    draw_runs(img, x + pad_x, y + pad_y, [(text, (0, 0, 0))], font, 0.04 * cap_h(font), shadow=False)


def style_band(img, cap, on_sale):
    w, h = img.size
    text = f"UNDER ${cap}!" if cap else FALLBACK_TEXT
    bh = round(0.085 * h)
    edges = edge_map(img)
    # Top tops from flush with the top edge; bottom ones down to flush
    # with the bottom edge, so the band can clear the shoes.
    candidates = [round(f / 100 * h) for f in range(0, 26)] + list(range(round(0.66 * h), h - bh + 1, max(1, h // 100)))
    candidates.append(h - bh)
    top = min(candidates, key=lambda t: busyness(edges, (0, t, w, t + bh), (w, h)))

    colour = deep_colour(img, (0, top, w, top + bh), value=0.16)
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(overlay).rectangle([0, top, w, top + bh], fill=colour + (200,))
    img.alpha_composite(overlay)
    font = fit(font_for_cap(0.5 * bh), text, 0.90 * w, 0.03 * bh)
    track = 0.03 * bh
    draw_runs(img, (w - text_width(font, text, track)) / 2, top + (bh - cap_h(font)) / 2,
              [(text, WHITE)], font, track)


STYLES = {"classic": style_classic, "fade": style_fade, "tag": style_tag, "band": style_band}


def render(preview_path, cap, on_sale, style="fade"):
    """Returns (pin image, path taken). Only fade has paths ("overlay" or
    "shrink") and returns a new canvas; the others draw on the photo."""
    with Image.open(preview_path) as src:
        img = ImageOps.exif_transpose(src).convert("RGBA")
    pin, path = STYLES[style](img, cap, on_sale) or (img, None)
    return pin.convert("RGB"), path


# ---------------------------------------------------------------- CLI

def batch_dirs(date):
    pattern = re.compile(rf"-{re.escape(date)}(-\d+)?$")
    return [d for d in all_dirs() if pattern.search(os.path.basename(d))]


def all_dirs():
    return sorted(d.rstrip("/\\") for d in glob.glob(os.path.join(REPO, "outfits", "*", "*", "")))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    ap.add_argument("campaigns", nargs="*", help="campaign folder(s)")
    ap.add_argument("--batch", metavar="DATE", help="every campaign whose slug ends in DATE, e.g. oct-12")
    ap.add_argument("--all", action="store_true", help="every campaign in outfits/")
    ap.add_argument("--style", choices=STYLES, default="fade", help="overlay style (default fade)")
    args = ap.parse_args()

    dirs = [os.path.abspath(c) for c in args.campaigns]
    if args.batch:
        dirs += batch_dirs(args.batch)
    if args.all:
        dirs += all_dirs()
    if not dirs:
        ap.error("give campaign folder(s), --batch DATE, or --all")
    explicit = {os.path.abspath(c) for c in args.campaigns}

    with open(PRODUCTS_JSON, encoding="utf-8") as f:
        products = json.load(f)

    made = skipped = failed = 0
    for d in dict.fromkeys(dirs):
        rel = os.path.relpath(d, REPO).replace(os.sep, "/")
        preview = find_preview(d)
        items = campaign_products(d, products)
        if preview is None or not items:
            why = "no outfit-preview image" if preview is None else "no products.json records"
            # Only a folder named on the command line is an error; batch
            # and --all runs just skip folders that aren't outfit campaigns.
            if d in explicit:
                print(f"ERROR {rel}: {why}")
                failed += 1
            else:
                print(f"skip  {rel}: {why}")
                skipped += 1
            continue
        cap = price_cap(items)
        on_sale = any((p.get("discount_percent") or 0) > 0 for p in items)
        label = (f"UNDER ${cap}" if cap else "no total") + (", on sale" if on_sale else "")
        pin, path = render(preview, cap, on_sale, args.style)
        pin.save(os.path.join(d, PIN_NAME), quality=92, optimize=True)
        how = f"{args.style}: {path}" if path else args.style
        print(f"made  {rel}/{PIN_NAME} [{how}]: {label}  ({len(items)} items)")
        made += 1

    print(f"\n{made} pin(s) made, {skipped} skipped, {failed} failed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
