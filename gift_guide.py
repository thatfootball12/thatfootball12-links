#!/usr/bin/env python3
"""
Gift guide listings in products.json: SHEIN products that appear only on
the holiday gift guide (gift-guide/index.html) and its Pinterest pins
(holiday-2026/pins/<pin>_holiday.png), with no product detail page.

They're in the catalog so the seller gates (sellers.py), the link checker
and CI cover them. A listing record has:
    detail_page_url  "gift-guide/index.html" (the page that lists it)
    holiday_pin      its pin id, e.g. "S02"
    outbound_url     the gift guide tile's affiliate link
    image            the tile's photo URL (remote; no local copy, so no
                     thumbnail)
    price            null (the gift guide shows a price tier, not a price)
It's in categories.json "hidden" (no tile on products/, and the outfit
generator skips it), its campaign holiday-2026 is in generator.json
"unthemed", and the page-based scripts (add_product_schema.py,
add_analytics.py, write_sitemap.py, make_product_pin.py) leave it out.
sync_catalog.py checks its tile and pin image still exist.

A gift guide product that already has a catalog record (same goods_id)
keeps that record and just gets holiday_pin added.
"""

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
        return set(re.findall(r'<a class="gg-shop" href="([^"]+)"', f.read()))


def audit(products):
    """Problems with listing records: a tile that's gone from the gift
    guide, or a missing holiday_pin / pin image (on any record that names
    a pin)."""
    links = page_links()
    out = []
    for p in products:
        if listing_only(p):
            if not p.get("holiday_pin"):
                out.append(f"{p['id']}: gift guide listing with no holiday_pin")
            if p.get("outbound_url") not in links:
                out.append(f"{p['id']}: its link is no longer on {PAGE}")
        img = pin_image(p)
        if img and not os.path.isfile(os.path.join(REPO, img.replace("/", os.sep))):
            out.append(f"{p['id']}: holiday pin image missing ({img})")
    return out
