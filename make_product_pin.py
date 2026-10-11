#!/usr/bin/env python3
"""
Makes the Pinterest pin image for a single SHEIN product: the product's
own photo with "SHOP NOW / UNDER $X!" text, saved as product-pin.jpg
in the product folder. The photo is never cropped, and the original is
never written to.

Usage:
    py -3 make_product_pin.py outfits/budget/budget-wedding-sept-10/belt
    py -3 make_product_pin.py --pick 20 --batch oct-12   (the 20 best deals
                                                          in that batch)
    py -3 make_product_pin.py --pick 20 --batch oct-12 --dry-run   (list only)

Layout: the same two paths as make_outfit_pin.py --style fade.
    shrink   (most photos) a 1000x1500 (2:3) pin: the photo scaled so
             330px of new space opens below it, centred, its sides and
             bottom blending softly into a deep colour sampled from the
             photo's bottom edge. The text goes in that new space, never
             over the photo.
    overlay  a photo already 2:3 or taller with at least 18% empty floor
             at the bottom keeps its shape (scaled to 1000 wide); the text
             goes in a fade over that floor.
Text: two centred Anton lines with a soft drop shadow, small
letter-spaced white "SHOP NOW" over "UNDER $X!" (UNDER white, price
gold #D4A017), the price line up to 70% of the pin's width, smaller if
the block doesn't fit the space.

Price: the product's products.json price, rounded UP. Under $10 to the
next whole dollar (4.20 -> UNDER $5); $10 and up to the next $5
(14.38 -> UNDER $15). An exact step goes one higher (15.00 -> UNDER $20)
so "under" stays true. No % off is ever printed.

SHEIN only: Amazon/Awin products and products without a price are
skipped, as are image_pending products (no photo yet).

--pick N --batch DATE: takes the batch's best N eligible SHEIN
products: any with discount_percent >= 20 first (biggest discount
first, ties cheaper first), then the rest cheapest first. Discounts
under 20% count for nothing.

Font: Anton (assets/fonts/, SIL Open Font License, see Anton-OFL.txt).
"""

import argparse
import colorsys
import json
import os
import re
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

REPO = os.path.dirname(os.path.abspath(__file__))
PRODUCTS_JSON = os.path.join(REPO, "products.json")
FONT_PATH = os.path.join(REPO, "assets", "fonts", "Anton-Regular.ttf")
PIN_NAME = "product-pin.jpg"
GOLD = (0xD4, 0xA0, 0x17)
WHITE = (255, 255, 255)
PIN_W, PIN_H = 1000, 1500    # shrink: pins are 2:3, Pinterest's standard
SPACE = 330                   # shrink: new space opened below the photo (px)
FADE = 0.08                   # shrink: photo-to-backdrop blend, fraction of PIN_H
SIDE_BLEND = 0.06             # shrink: soft side edges, fraction of the photo width
TEXT_WIDTH = 0.70             # widest the price line may get
TALL = 1.5                    # overlay: height/width at least this (2:3 or taller)
MIN_CALM = 0.18               # overlay: empty floor needed at the bottom
BIG_DISCOUNT = 20             # --pick: discount_percent that ranks first
CALM_EDGE = 20                # busiest patch an "empty floor" row may have (0-255 edges)


# ---------------------------------------------------------------- prices

def price_cap(price):
    """Dollar figure for "UNDER $X": next whole dollar under $10, next $5
    from $10 up, always strictly above the price."""
    cents = round(price * 100)
    if cents < 1000:
        return cents // 100 + 1
    return (cents // 500 + 1) * 5


def eligible(p):
    return (p.get("retailer") == "SHEIN" and p.get("price") is not None
            and not p.get("image_pending") and p.get("image"))


def why_ineligible(p):
    if p.get("retailer") != "SHEIN":
        return f"{p.get('retailer')} product"
    if p.get("price") is None:
        return "no price"
    return "no photo yet"


# ---------------------------------------------------------------- drawing

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


def draw_runs(img, x, cap_y, runs, font, tracking=0):
    """Draw [(text, colour), ...] left to right starting at x, with the
    tops of the capitals at cap_y, over a soft drop shadow."""
    h = img.size[1]
    y = cap_y - cap_top(font)
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    _runs(ImageDraw.Draw(layer), x + 0.004 * h, y + 0.004 * h, runs, font, tracking, (0, 0, 0, 150))
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(0.006 * h)))
    _runs(ImageDraw.Draw(img), x, y, runs, font, tracking, None)


def _runs(draw, x, y, runs, font, tracking, override):
    for text, colour in runs:
        for ch in text:
            draw.text((x, y), ch, font=font, fill=override or colour + (255,))
            x += font.getlength(ch) + tracking


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


def calm_bottom(img):
    """Fraction of the photo's height, measured up from the bottom, that's
    empty: every 2% band in it has no 1/12-width patch with more than
    CALM_EDGE edge strength. The one-pixel border is skipped, since edge
    filters always fire there."""
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


def vertical_fade(img, y0, y1, colour, max_alpha=255):
    """Rows y0..y1 go from clear to max_alpha of colour (smoothstep)."""
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    for y in range(y0, y1):
        t = (y - y0 + 1) / (y1 - y0)
        d.line([(0, y), (img.size[0], y)], fill=colour + (round(max_alpha * t * t * (3 - 2 * t)),))
    img.alpha_composite(overlay)


def draw_text(img, top, bottom, cap):
    """"SHOP NOW" over "UNDER $X!", centred between top and bottom: the
    price line as wide as TEXT_WIDTH allows, smaller if the block is
    taller than the space."""
    w = img.size[0]
    top_run = ("SHOP NOW", WHITE)
    big_runs = [("UNDER ", WHITE), (f"${cap}!", GOLD)]
    big_text = "".join(t for t, _ in big_runs)

    def block(big):
        small = font_for_cap(0.5 * cap_h(big))
        track = 0.3 * cap_h(small)
        gap = 0.6 * cap_h(small)
        return small, track, gap, cap_h(small) + gap + cap_h(big)

    big = fit(font_for_cap(img.size[1]), big_text, TEXT_WIDTH * w)
    small, track, gap, bh = block(big)
    while bh > bottom - top and big.size > 8:
        big = ImageFont.truetype(FONT_PATH, big.size - 2)
        small, track, gap, bh = block(big)

    y = top + (bottom - top - bh) / 2
    draw_runs(img, (w - text_width(small, top_run[0], track)) / 2, y, [top_run], small, track)
    draw_runs(img, (w - text_width(big, big_text)) / 2, y + cap_h(small) + gap, big_runs, big)


def render(photo_path, cap):
    """Returns (pin image, path taken: "overlay" or "shrink")."""
    with Image.open(photo_path) as src:
        img = ImageOps.exif_transpose(src).convert("RGBA")
    w, h = img.size
    if h / w >= TALL - 0.005:
        calm = calm_bottom(img)
        if calm >= MIN_CALM:
            return render_overlay(img, cap, calm).convert("RGB"), "overlay"
    return render_shrink(img, cap).convert("RGB"), "shrink"


def render_overlay(img, cap, calm):
    w, h = img.size
    pin = img.resize((PIN_W, round(h * PIN_W / w)), Image.LANCZOS)
    pw, ph = pin.size
    floor_top = round(ph * (1 - calm))
    colour = deep_colour(pin, (0, floor_top, pw, ph))
    # Fade from a little above the floor, ending at 85% so the floor
    # still reads as floor, not as a pasted bar.
    vertical_fade(pin, max(0, floor_top - round(0.06 * ph)), ph, colour, max_alpha=round(255 * 0.85))
    draw_text(pin, floor_top + 0.1 * (ph - floor_top), ph - 0.04 * ph, cap)
    return pin


def render_shrink(img, cap):
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
    # The text stays in the new space, clear of the photo.
    draw_text(pin, ph + 0.02 * PIN_H, PIN_H - 0.045 * PIN_H, cap)
    return pin


# ---------------------------------------------------------------- selection

def batch_products(products, date):
    pattern = re.compile(rf"-{re.escape(date)}(-\d+)?$")
    return [p for p in products if pattern.search(p.get("campaign") or "")]


def pick(products, n):
    """Best n: discount_percent >= BIG_DISCOUNT first (biggest first),
    then everything else cheapest first. Smaller discounts don't count."""
    def key(p):
        disc = p.get("discount_percent") or 0
        if disc >= BIG_DISCOUNT:
            return (0, -disc, p["price"])
        return (1, p["price"], 0)
    return sorted(products, key=key)[:n]


# ---------------------------------------------------------------- CLI

def product_for_dir(products, d):
    rel = os.path.relpath(d, REPO).replace(os.sep, "/").rstrip("/") + "/index.html"
    return next((p for p in products if p.get("detail_page_url") == rel), None)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    ap.add_argument("products", nargs="*", help="product folder(s)")
    ap.add_argument("--pick", type=int, metavar="N", help="the N best SHEIN deals in --batch")
    ap.add_argument("--batch", metavar="DATE", help="campaign date, e.g. oct-12 (with --pick)")
    ap.add_argument("--dry-run", action="store_true", help="list what would be made, write nothing")
    args = ap.parse_args()
    if bool(args.pick) != bool(args.batch):
        ap.error("--pick and --batch go together")
    if not args.products and not args.pick:
        ap.error("give product folder(s), or --pick N --batch DATE")

    with open(PRODUCTS_JSON, encoding="utf-8") as f:
        products = json.load(f)

    todo, failed = [], 0
    for d in args.products:
        p = product_for_dir(products, os.path.abspath(d))
        if p is None:
            print(f"ERROR {d}: no products.json record")
            failed += 1
        elif not eligible(p):
            print(f"skip  {p['id']}: {why_ineligible(p)}")
        else:
            todo.append(p)
    if args.pick:
        pool = batch_products(products, args.batch)
        ok = [p for p in pool if eligible(p)]
        chosen = pick(ok, args.pick)
        print(f"{args.batch}: {len(pool)} products, {len(ok)} eligible SHEIN, picked {len(chosen)}\n")
        print(f"  {'#':>2}  {'price':>7}  {'disc':>4}  {'tag':<9}  product")
        for i, p in enumerate(chosen, 1):
            disc = f"{p['discount_percent']}%" if p.get("discount_percent") else "-"
            print(f"  {i:>2}  {p['price']:>7.2f}  {disc:>4}  UNDER ${price_cap(p['price']):<3}  {p['id']}")
        print()
        todo += [p for p in chosen if p not in todo]

    made = 0
    for p in todo:
        photo = os.path.join(REPO, p["image"])
        out = os.path.join(os.path.dirname(os.path.join(REPO, p["detail_page_url"])), PIN_NAME)
        if not os.path.exists(photo):
            print(f"ERROR {p['id']}: photo missing ({p['image']})")
            failed += 1
            continue
        if os.path.abspath(out) == os.path.abspath(photo):
            print(f"ERROR {p['id']}: photo is named {PIN_NAME}; refusing to overwrite it")
            failed += 1
            continue
        if args.dry_run:
            continue
        pin, path = render(photo, price_cap(p["price"]))
        pin.save(out, quality=92, optimize=True)
        print(f"made  {os.path.relpath(out, REPO)} [{path}]: UNDER ${price_cap(p['price'])}")
        made += 1

    if not args.dry_run:
        print(f"\n{made} pin(s) made, {failed} failed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
