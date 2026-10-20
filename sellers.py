#!/usr/bin/env python3
"""
The SHEIN "seller" field on products.json records, shared by the pin
scripts, sync_catalog.py and set_seller.py.

Every SHEIN record carries seller:
    "shein"        sold by SHEIN itself
    "marketplace"  sold by a third-party store on SHEIN's marketplace
    "unchecked"    nobody has looked yet (the default for records that
                   existed before the field did)
Amazon and Awin records have no seller field.

Marketplace products never get a Pinterest pin: make_product_pin.py
refuses them and make_pinterest_csv.py blocks any pin of one. Unchecked
products still get pins, with a warning, until someone checks them.

unchecked_sellers.txt (written by set_seller.py) lists every unchecked
SHEIN product, newest batch first, with its goods id (to search on the
SHEIN Affiliate site) and a plain ca.shein.com product URL. It never
carries the affiliate (onelink) link: opening those would count as a
self-click.
"""

import os
import re

REPO = os.path.dirname(os.path.abspath(__file__))
UNCHECKED_TXT = os.path.join(REPO, "unchecked_sellers.txt")

SHEIN, MARKETPLACE, UNCHECKED = "shein", "marketplace", "unchecked"
VALUES = (SHEIN, MARKETPLACE, UNCHECKED)

REFUSED = "sold by a third-party marketplace store, not SHEIN; no pin"
UNCHECKED_WARNING = ("seller unchecked; confirm it's sold by SHEIN, then "
                     "py -3 set_seller.py <id> shein|marketplace")


def is_shein(p):
    return p.get("retailer") == "SHEIN"


def seller(p):
    return p.get("seller") if is_shein(p) else None


def refused(p):
    return seller(p) == MARKETPLACE


def unchecked(p):
    return seller(p) == UNCHECKED


def audit(products):
    """Returns (errors, counts). Errors: a SHEIN record with no seller or
    one that isn't in VALUES, and a non-SHEIN record that has one."""
    errors = []
    counts = {v: 0 for v in VALUES}
    for p in products:
        if is_shein(p):
            v = p.get("seller")
            if v is None:
                errors.append(f"{p['id']}: SHEIN record has no seller")
            elif v not in VALUES:
                errors.append(f"{p['id']}: seller {v!r} isn't one of {', '.join(VALUES)}")
            else:
                counts[v] += 1
        elif "seller" in p:
            errors.append(f"{p['id']}: {p.get('retailer')} record has a seller field "
                          f"(SHEIN only)")
    return errors, counts


def unchecked_list(products):
    """Unchecked SHEIN records, newest batch first (by added, then
    campaign, then id)."""
    rows = [p for p in products if unchecked(p)]
    rows.sort(key=lambda p: (p.get("campaign") or "", p["id"]))
    rows.sort(key=lambda p: p.get("added") or "", reverse=True)
    return rows


def plain_url(p):
    """ca.shein.com product page with no affiliate parameters, in SHEIN's
    own <name>-p-<goods_id>.html form (the id is what SHEIN routes on)."""
    if not p.get("goods_id"):
        return ""
    slug = re.sub(r"[^A-Za-z0-9]+", "-", p.get("name") or "").strip("-") or "product"
    return f"https://ca.shein.com/{slug}-p-{p['goods_id']}.html"


def write_unchecked(products):
    """Writes unchecked_sellers.txt; returns how many products it lists."""
    rows = unchecked_list(products)
    lines = [
        "# SHEIN products whose seller hasn't been checked, newest batch first.",
        "# Search each goods id on the SHEIN Affiliate site (or open the plain URL)",
        "# and see who it's sold by. These are deliberately NOT affiliate links:",
        "# never open a product's onelink link to check it. To record results, copy",
        "# lines into a file, add shein or marketplace to the end of each, and run",
        "#     py -3 set_seller.py --from <file>",
        "# (or one at a time: py -3 set_seller.py <id> shein|marketplace).",
        "# This file is rewritten by set_seller.py; don't edit it by hand.",
        "#",
        "# id<TAB>goods id<TAB>plain SHEIN URL",
    ]
    last = None
    for p in rows:
        if p.get("added") != last:
            last = p.get("added")
            n = sum(1 for q in rows if q.get("added") == last)
            lines += ["", f"# added {last or 'unknown'} ({n})"]
        lines.append(f"{p['id']}\t{p.get('goods_id') or '(no goods id)'}\t{plain_url(p)}")
    with open(UNCHECKED_TXT, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return len(rows)
