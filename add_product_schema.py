#!/usr/bin/env python3
"""
Writes a schema.org Product JSON-LD block into the <head> of every SHEIN
product detail page, generated from products.json. Safe to re-run: the
block lives between marker comments and is replaced in place, so a
changed price or description in products.json/the page just gets
rewritten on the next run.

Usage:
    python add_product_schema.py            (write/refresh blocks)
    python add_product_schema.py --check    (report only, change nothing)

sync_catalog.py imports expected_block() from here and reports any SHEIN
page whose block is missing or stale, so run this whenever that report
flags one (it's on the weekly batch checklist in CLAUDE.md).

Scope, deliberately narrow (see the product-schema-markup PR for the
research behind each choice):

  - SHEIN only. Amazon pages show "Check price on Amazon" per the
    affiliate price-compliance convention, and Google's structured data
    guidelines say "Don't mark up content that is not visible to readers
    of the page" — so their price can't go in markup. Without a price,
    review, or rating, a Product isn't eligible for a product snippet at
    all, so Amazon pages get no block. Same for the one Awin page, which
    shows "Shop Link" and has no price.
  - No `availability`. The pages don't show stock status and nothing
    here can verify it (check_affiliate_links.py can't detect sold-out
    items), so claiming InStock would be unverified.
  - `price` is the price the page displays (for discounted items, the
    discounted price — the page doesn't show an original price, so none
    is marked up).
  - image_pending pages (photo doesn't exist yet) get no block until the
    photo lands. Google's Rich Results Test passes them as product
    snippets but fails them as merchant listings ("Missing field image"
    is critical there), which would show as invalid items in Search
    Console. Once image_pending flips to false, sync_catalog.py reports
    the page as missing a block and a re-run adds it.
  - Any page that has a block but shouldn't (e.g. a product whose
    retailer changed) has the block removed.

Pinterest doesn't document JSON-LD support for Rich Pins (only Open
Graph and schema.org microdata), and its product pins require the
product to be purchasable directly on the linked site — so this is for
Google search. Pinterest keeps reading the existing og:/product: meta
tags.
"""

import argparse
import html
import json
import os
import re

REPO = os.path.dirname(os.path.abspath(__file__))
PRODUCTS_JSON = os.path.join(REPO, "products.json")
SITE = "https://thatfootball12.github.io/thatfootball12-links/"

START = "<!-- product-schema:start -->"
END = "<!-- product-schema:end -->"
BLOCK_RE = re.compile(r"[ \t]*" + re.escape(START) + r".*?" + re.escape(END) + r"[ \t]*\r?\n?", re.DOTALL)
OG_DESC_RE = re.compile(r'<meta property="og:description" content="([^"]*)"')


def load_products():
    with open(PRODUCTS_JSON, encoding="utf-8") as f:
        return json.load(f)


def page_path(p):
    return os.path.join(REPO, p["detail_page_url"].replace("/", os.sep))


def read_page(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def write_page(path, text):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def wants_block(p):
    return (p["retailer"] == "SHEIN" and p["price"] is not None and bool(p["currency"])
            and not p["image_pending"] and bool(p["image"]))


def expected_block(p, page_html):
    """The exact marker-wrapped block this product's page should carry,
    using the page's own line endings. None if the product gets no block."""
    if not wants_block(p):
        return None
    data = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": p["name"],
        "image": SITE + p["image"],
    }
    m = OG_DESC_RE.search(page_html)
    if m:
        data["description"] = html.unescape(m.group(1))
    data["url"] = SITE + re.sub(r"index\.html$", "", p["detail_page_url"])
    data["offers"] = {
        "@type": "Offer",
        "price": f"{p['price']:.2f}",
        "priceCurrency": p["currency"],
        "url": p["outbound_url"],
    }
    body = json.dumps(data, indent=2, ensure_ascii=False).replace("</", "<\\/")
    nl = "\r\n" if "\r\n" in page_html else "\n"
    lines = [START, '<script type="application/ld+json">'] + body.split("\n") + ["</script>", END]
    return nl.join(lines) + nl


def current_block(page_html):
    m = BLOCK_RE.search(page_html)
    if not m:
        return None
    return m.group(0).strip(" \t")


def apply(page_html, block):
    """Return page_html with its block replaced/inserted/removed."""
    stripped = BLOCK_RE.sub("", page_html)
    if block is None:
        return stripped
    idx = stripped.find("</head>")
    if idx == -1:
        raise ValueError("no </head>")
    return stripped[:idx] + block + stripped[idx:]


def status(p, page_html):
    """'ok', 'missing', 'stale', or 'unwanted' (block present but shouldn't be)."""
    want = expected_block(p, page_html)
    have = current_block(page_html)
    if want is None:
        return "unwanted" if have is not None else "ok"
    if have is None:
        return "missing"
    # Compare ignoring line endings: git's autocrlf converts them on
    # checkout/commit, which isn't a content change.
    same = have.replace("\r\n", "\n") == want.replace("\r\n", "\n")
    return "ok" if same else "stale"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="report only, change nothing")
    args = ap.parse_args()

    counts = {"ok": 0, "missing": 0, "stale": 0, "unwanted": 0}
    changed = []
    for p in load_products():
        path = page_path(p)
        if not os.path.isfile(path):
            continue  # sync_catalog.py reports these
        page = read_page(path)
        st = status(p, page)
        counts[st] += 1
        if st == "ok":
            continue
        changed.append((st, p["detail_page_url"]))
        if not args.check:
            write_page(path, apply(page, expected_block(p, page)))

    verb = "would change" if args.check else "changed"
    print(f"Up to date: {counts['ok']}")
    print(f"Missing block: {counts['missing']}  Stale block: {counts['stale']}  "
          f"Block on a page that shouldn't have one: {counts['unwanted']}")
    for st, rel in changed:
        print(f"  {verb} ({st}): {rel}")


if __name__ == "__main__":
    main()
