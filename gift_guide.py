#!/usr/bin/env python3
"""
Gift guide listings in products.json: products that appear only on the
holiday gift guide (gift-guide/index.html), with no product detail page.
They can be SHEIN, Amazon or Awin.

They're in the catalog so the seller gates (sellers.py), the link and tag
checks and CI cover them. A listing record has:
    detail_page_url  "gift-guide/index.html" (the page that lists it)
    outbound_url     the gift guide tile's affiliate link
    image            the tile's photo (a remote URL on the older SHEIN
                     records, gift-guide/img/... on newer ones; no
                     thumbnail either way)
    price            null (the gift guide shows a price tier, not a price)
    holiday_pin      optional: its pin id, e.g. "S02", once it has a pin
                     (holiday-2026/pins/<pin>_holiday.png). Leave it off
                     until then: pins come later (make_gift_pin.py).
    asin             Amazon listings: the product's ASIN
    merchant         Awin listings: the store, e.g. "Moosehill"
    goods_id, seller SHEIN listings, as on any SHEIN record
It's in categories.json "hidden" (no tile on products/, and the outfit
generator skips it), its campaign holiday-2026 is in generator.json
"unthemed", and the page-based scripts (add_product_schema.py,
add_analytics.py, write_sitemap.py, make_product_pin.py) leave it out.
sync_catalog.py checks each listing's tile, its required fields, that
it's hidden, and any pin image it names.

A gift guide product that already has a catalog record (same goods_id)
keeps that record and just gets holiday_pin added.
"""

import html as htmllib
import json
import os
import re

REPO = os.path.dirname(os.path.abspath(__file__))
PAGE = "gift-guide/index.html"
PIN_DIR = "holiday-2026/pins"


def listing_only(p):
    return p.get("detail_page_url") == PAGE


def pin_image(p):
    """Repo-relative path of the record's holiday pin image, or None."""
    pin = p.get("holiday_pin")
    return f"{PIN_DIR}/{pin}_holiday.png" if pin else None


def page_links():
    """Every gift guide tile's shop link."""
    path = os.path.join(REPO, PAGE.replace("/", os.sep))
    if not os.path.isfile(path):
        return set()
    with open(path, encoding="utf-8") as f:
        return {htmllib.unescape(u) for u in re.findall(r'<a class="gg-shop" href="([^"]+)"', f.read())}


def card_key(card_id):
    """"S1", "S01" and "s01" all name the same card; returns "S1"."""
    m = re.fullmatch(r"([A-Za-z]+)0*(\d+)", (card_id or "").strip())
    return f"{m.group(1).upper()}{m.group(2)}" if m else (card_id or "")


def shein_cards():
    """Every SHEIN tile on the gift guide, in page order: a list of
    {card, name, link}. link is None when the tile's shop link can't be
    read, so a broken tile shows up instead of being skipped."""
    path = os.path.join(REPO, PAGE.replace("/", os.sep))
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as f:
        html = f.read()
    out = []
    for card, body in re.findall(r'<article class="card-tile" data-id="([^"]+)"(.*?)</article>', html, re.S):
        if 'class="retailer shein"' not in body:
            continue
        link = re.search(r'<a class="gg-shop" href="([^"]+)"', body)
        name = re.search(r'<h3 class="prod-name">([^<]+)</h3>', body)
        out.append({"card": card_key(card), "name": htmllib.unescape(name.group(1).strip()) if name else card,
                    "link": link.group(1) if link else None})
    return out


def hidden_ids():
    with open(os.path.join(REPO, "categories.json"), encoding="utf-8") as f:
        return set(json.load(f)["hidden"])


def audit(products):
    """Problems with listing records: a tile that's gone from the gift
    guide, a listing that shows on products/ or has a price, an Amazon
    listing whose asin isn't in its link, an Awin listing with no
    merchant, or a named pin image that's missing (on any record)."""
    links = page_links()
    hidden = hidden_ids()
    out = []
    for p in products:
        if listing_only(p):
            url = p.get("outbound_url") or ""
            if url not in links:
                out.append(f"{p['id']}: its link is no longer on {PAGE}")
            if p["id"] not in hidden:
                out.append(f"{p['id']}: gift guide listing not in categories.json hidden")
            if p.get("price") is not None:
                out.append(f"{p['id']}: gift guide listing with a price (should be null)")
            if p.get("retailer") == "Amazon" and (not p.get("asin") or p["asin"] not in url):
                out.append(f"{p['id']}: Amazon listing whose asin isn't in its link")
            if p.get("retailer") == "Awin" and not p.get("merchant"):
                out.append(f"{p['id']}: Awin listing with no merchant")
        img = pin_image(p)
        if img and not os.path.isfile(os.path.join(REPO, img.replace("/", os.sep))):
            out.append(f"{p['id']}: holiday pin image missing ({img})")
    return out
