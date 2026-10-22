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
  - `availability` is OutOfStock for any product confirmed dead in
    data/dead_links.json (which includes the hand-added `manual:` SOLD
    OUT entries, check_affiliate_links.py can't detect sold-out items),
    else InStock. When the weekly link check confirms a new dead
    product, item 4 of sync_catalog.py reports its page as stale until
    this runs again.
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
product to be purchasable directly on the linked site — so the block is
for Google search. Pinterest reads the og:/product: meta tags, which the
pages carry from when they were written. This script keeps three of
them in line, in place, without adding a marker block:

  - og:title (every product page, Amazon and Awin too) is the page's
    short <title> without " • ThatFootball12" (e.g. "LA Graphic Knit
    Tee"). The full product name stays in the page body and the block.
    When the full name has a brand from KNOWN_BRANDS that the short
    title leaves out, the brand goes in front ("New Era 9FORTY
    Adjustable Hat"). Add a brand there to have it kept.
  - og:price:amount / og:price:currency (SHEIN only) copy the page's
    product:price:amount / product:price:currency tags, right after
    them, so both spellings Rich Pin parsers look for are there.
    Amazon pages show no price and have no price tags; the Awin page's
    product:price tags are left alone.
  - og:availability (SHEIN only) is "out of stock" for a product
    confirmed dead, the same rule as the block's availability, else
    "instock".
"""

import argparse
import functools
import html
import json
import os
import re

import check_affiliate_links
import gift_guide

REPO = os.path.dirname(os.path.abspath(__file__))
PRODUCTS_JSON = os.path.join(REPO, "products.json")
SITE = "https://thatfootball12.github.io/thatfootball12-links/"

START = "<!-- product-schema:start -->"
END = "<!-- product-schema:end -->"
BLOCK_RE = re.compile(r"[ \t]*" + re.escape(START) + r".*?" + re.escape(END) + r"[ \t]*\r?\n?", re.DOTALL)
OG_DESC_RE = re.compile(r'<meta property="og:description" content="([^"]*)"')

TITLE_RE = re.compile(r"<title>(.*?)</title>", re.DOTALL)
TITLE_SUFFIX = " • ThatFootball12"
OG_TITLE_RE = re.compile(r'(<meta property="og:title" content=")[^"]*(")')
OG_AVAILABILITY_RE = re.compile(r'(<meta property="og:availability" content=")[^"]*(")')
PRODUCT_PRICE_LINE_RE = re.compile(r'^[ \t]*<meta property="product:price:(?:amount|currency)"[^>]*>\r?\n', re.M)
OG_PRICE_LINE_RE = re.compile(r'^[ \t]*<meta property="og:price:(?:amount|currency)"[^>]*>\r?\n', re.M)

# Brands kept at the front of the short og:title: (display name, pattern
# matched case-insensitively against the full product name and the short
# title). Well-known labels only, not Amazon house brands; no "Jordan"
# (player names).
KNOWN_BRANDS = [
    ("New Era", r"new era"),
    ("Fanatics", r"fanatics"),
    ("'47", r"['’]47"),
    ("Mitchell & Ness", r"mitchell (?:&|&amp;|and) ness"),
    ("Nike", r"nike"),
    ("Adidas", r"adidas"),
    ("Asics", r"asics"),
    ("Under Armour", r"under armour"),
    ("Timberland", r"timberland"),
    ("Champion", r"champion"),
    ("Levi's", r"levi(?:['’]?s| strauss)"),
    ("Lacoste", r"lacoste"),
    ("Timex", r"timex"),
    ("Hanes", r"hanes"),
    ("Gildan", r"gildan"),
    ("Fruit of the Loom", r"fruit of the loom"),
    ("Puma", r"puma"),
    ("Reebok", r"reebok"),
    ("New Balance", r"new balance"),
    ("Converse", r"converse"),
    ("Vans", r"vans"),
    ("Carhartt", r"carhartt"),
    ("The North Face", r"(?:the )?north face"),
    ("Columbia", r"columbia"),
    ("Ralph Lauren", r"(?:polo )?ralph lauren"),
    ("Tommy Hilfiger", r"tommy hilfiger"),
    ("Calvin Klein", r"calvin klein"),
    ("Dickies", r"dickies"),
    ("Wrangler", r"wrangler"),
    ("Skechers", r"skechers"),
    ("Dr. Martens", r"dr\.? martens"),
    ("Ray-Ban", r"ray-?ban"),
    ("Oakley", r"oakley"),
    ("Casio", r"casio"),
    ("Fossil", r"fossil"),
]
BRAND_RES = [(name, re.compile(r"(?<!\w)(?:%s)(?!\w)" % pat, re.I)) for name, pat in KNOWN_BRANDS]


def brand_prefixed(short, full_name):
    """short with the brand (earliest in full_name) in front, unless it's
    already in short or the product has no known brand."""
    hits = [(m.start(), name, rx) for name, rx in BRAND_RES for m in [rx.search(full_name)] if m]
    if not hits:
        return short
    _, name, rx = min(hits, key=lambda h: h[0])
    return short if rx.search(short) else f"{name} {short}"


@functools.lru_cache(maxsize=None)
def sold_out_ids():
    """Ids confirmed dead in data/dead_links.json (manual SOLD OUT entries included)."""
    return frozenset(check_affiliate_links.confirmed_ids())


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
        "availability": "https://schema.org/" + ("OutOfStock" if p["id"] in sold_out_ids() else "InStock"),
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
    """Return page_html with its block replaced (in place), inserted or removed."""
    if block is not None and BLOCK_RE.search(page_html):
        return BLOCK_RE.sub(lambda m: block, page_html, count=1)
    stripped = BLOCK_RE.sub("", page_html)
    if block is None:
        return stripped
    idx = stripped.find("</head>")
    if idx == -1:
        raise ValueError("no </head>")
    return stripped[:idx] + block + stripped[idx:]


def apply_meta(p, page_html):
    """Return page_html with its og:title, og:price:* and og:availability
    tags brought in line (see the module docstring)."""
    page = page_html
    t = TITLE_RE.search(page)
    if t:
        short = html.unescape(t.group(1).strip())
        if short.endswith(TITLE_SUFFIX):
            short = short[:-len(TITLE_SUFFIX)]
        short = brand_prefixed(short, p["name"])
        page = OG_TITLE_RE.sub(lambda m: m.group(1) + html.escape(short) + m.group(2), page, count=1)
    if p["retailer"] != "SHEIN":
        return page
    page = OG_PRICE_LINE_RE.sub("", page)
    price_lines = list(PRODUCT_PRICE_LINE_RE.finditer(page))
    if price_lines:
        og = "".join(m.group(0).replace('"product:price:', '"og:price:', 1) for m in price_lines)
        end = price_lines[-1].end()
        page = page[:end] + og + page[end:]
    availability = "out of stock" if p["id"] in sold_out_ids() else "instock"
    page = OG_AVAILABILITY_RE.sub(lambda m: m.group(1) + availability + m.group(2), page, count=1)
    return page


def status(p, page_html):
    """'ok', 'missing', 'stale', 'unwanted' (block present but shouldn't
    be), or 'meta' (block fine, og:title/og:price/og:availability not)."""
    want = expected_block(p, page_html)
    have = current_block(page_html)
    if want is None:
        if have is not None:
            return "unwanted"
    elif have is None:
        return "missing"
    # Compare ignoring line endings: git's autocrlf converts them on
    # checkout/commit, which isn't a content change.
    elif have.replace("\r\n", "\n") != want.replace("\r\n", "\n"):
        return "stale"
    return "ok" if apply_meta(p, page_html) == page_html else "meta"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="report only, change nothing")
    args = ap.parse_args()

    counts = {"ok": 0, "missing": 0, "stale": 0, "unwanted": 0, "meta": 0}
    changed = []
    for p in load_products():
        if gift_guide.listing_only(p):
            continue  # no detail page (gift_guide.py)
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
            write_page(path, apply_meta(p, apply(page, expected_block(p, page))))

    verb = "would change" if args.check else "changed"
    print(f"Up to date: {counts['ok']}")
    print(f"Missing block: {counts['missing']}  Stale block: {counts['stale']}  "
          f"Block on a page that shouldn't have one: {counts['unwanted']}  "
          f"Meta tags only: {counts['meta']}")
    for st, rel in changed:
        print(f"  {verb} ({st}): {rel}")


if __name__ == "__main__":
    main()
