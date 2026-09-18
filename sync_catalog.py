#!/usr/bin/env python3
"""
Scans outfits/ and videos/ for product detail pages and cross-checks them
against products.json, the master catalog data file that products/index.html
renders from.

Usage in Claude Code:
    "Run sync_catalog.py"              (report only, default)
    "Run sync_catalog.py --append"     (also append missing records)

Why this exists: batches get built by hand-authoring outfit pages (there is
no script in this repo that generates them — parse_shein.py, classify.py,
fetch_images.py, and build_outfits.py only get you to a proposed grouping in
outfits.csv; someone still creates the actual directories, downloads photos,
writes the detail pages, and inserts category-page cards). It's easy for
that manual step to finish a batch without also updating products.json,
since nothing enforces it — that's exactly what happened to the Sept 15
business-casual, old-money, and streetwear batches. Run this as the last
step of every weekly batch, before committing, to catch it immediately
instead of leaving products silently invisible in the catalog.

This script deliberately does NOT try to publish new outfit pages itself —
see the "Two paths" note in the module docstring history / commit message
for why a narrower safety net was chosen over a full publisher.

Scope:
  - A "product detail page" is any outfits/<theme>/<campaign>/<slug>/index.html
    or videos/<category>/<campaign>/<slug>/index.html file (4 directories
    deep). The 20 legacy link-list campaign pages and the redirect-stub
    folders at the repo root are naturally excluded: legacy pages have no
    4-deep children, and the redirect stubs live outside outfits/ and
    videos/ entirely.

Report (always runs):
  1. Detail pages on disk with no products.json record.
  2. products.json records whose detail page no longer exists on disk.
  3. products.json records whose thumbnail file is missing on disk.

Append (--append only):
  For each detail page found in (1), build a record the same way the
  original catalog extraction did:
    - name from <h1>
    - price/currency: SHEIN and Awin from the page's own
      product:price:amount / product:price:currency meta tags (matches the
      page's own displayed price); Amazon by outbound link domain
      (amazon.ca -> CAD, amazon.com -> USD, amzn.to -> resolve the redirect
      to see which). Never falls back to a guess: if no signal exists for
      a field, that field is left null and the product is flagged in the
      report rather than silently included with made-up data.
    - retailer classified by the outbound link's domain, same rule as the
      original extraction (amazon.com/amazon.ca/amzn.to, onelink.shein.com,
      awin1.com/tidd.ly).
    - theme/campaign/source/slug derived from the folder path.
    - a 424px-wide thumbnail derivative generated at quality 85, matching
      the rest of the catalog (never upscaled).
  item_type and data_new have no source anywhere outside human judgment —
  they are never inferred. Appended records get item_type: null and
  data_new: null, and are listed in the report as needing manual review
  before they'll filter correctly or show a "New This Week" badge.
"""

import argparse
import glob
import html
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from PIL import Image

REPO = os.path.dirname(os.path.abspath(__file__))
PRODUCTS_JSON = os.path.join(REPO, "products.json")
THUMB_TARGET_WIDTH = 424
THUMB_QUALITY = 85

IMG_META_AMOUNT_RE = re.compile(r'<meta property="product:price:amount" content="([^"]*)"')
IMG_META_CURRENCY_RE = re.compile(r'<meta property="product:price:currency" content="([^"]*)"')
SHOP_LINK_RE = re.compile(r'<a class="shop" href="([^"]+)"')
H1_RE = re.compile(r'<h1>(.*?)</h1>', re.DOTALL)
IMG_TAG_RE = re.compile(r'<img src="([^"]+)"')


def find_detail_pages():
    pages = []
    for src in ("outfits", "videos"):
        pattern = os.path.join(REPO, src, "*", "*", "*", "index.html")
        for path in glob.glob(pattern):
            rel = os.path.relpath(path, REPO).replace(os.sep, "/")
            parts = rel.split("/")
            # src/theme/campaign/slug/index.html
            if len(parts) != 5:
                continue
            pages.append(rel)
    return sorted(pages)


def load_products():
    with open(PRODUCTS_JSON, encoding="utf-8") as f:
        return json.load(f)


def save_products(products):
    with open(PRODUCTS_JSON, "w", encoding="utf-8") as f:
        json.dump(products, f, indent=2, ensure_ascii=False)


def classify_retailer(url):
    if not url:
        return None
    u = url.lower()
    if "amazon.com" in u or "amazon.ca" in u or "amzn.to" in u:
        return "Amazon"
    if "shein.com" in u:
        return "SHEIN"
    if "awin1.com" in u or "tidd.ly" in u:
        return "Awin"
    return "Other"


_redirect_cache = {}


def resolve_redirect(url):
    if url in _redirect_cache:
        return _redirect_cache[url]
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            final = resp.geturl()
        _redirect_cache[url] = ("ok", final)
    except Exception as e:
        _redirect_cache[url] = ("error", f"{type(e).__name__}: {e}")
    time.sleep(1.5)
    return _redirect_cache[url]


def amazon_currency(url):
    """Returns (currency, source) or (None, reason) — never guesses."""
    u = url.lower()
    if "amazon.ca" in u:
        return "CAD", "link domain"
    if "amazon.com" in u:
        return "USD", "link domain"
    if "amzn.to" in u:
        status, val = resolve_redirect(url)
        if status != "ok":
            return None, f"unresolved redirect ({val})"
        vl = val.lower()
        if "amazon.ca" in vl:
            return "CAD", "resolved redirect"
        if "amazon.com" in vl:
            return "USD", "resolved redirect"
        return None, f"redirect landed on unrecognized domain ({val})"
    return None, "not an amazon.com/amazon.ca/amzn.to link"


def build_record(rel_path):
    """Returns (record_dict, flags_list). record_dict is None if the page
    couldn't be read at all; otherwise always returned even with some
    fields null/flagged, so the caller can decide what to do with it."""
    flags = []
    abs_path = os.path.join(REPO, rel_path.replace("/", os.sep))
    with open(abs_path, encoding="utf-8") as f:
        content = f.read()

    parts = rel_path.split("/")
    source, theme, campaign, slug = parts[0], parts[1], parts[2], parts[3]

    h1_m = H1_RE.search(content)
    name = html.unescape(h1_m.group(1).strip()) if h1_m else None
    if name is None:
        flags.append("no <h1> found — name could not be determined")

    shop_m = SHOP_LINK_RE.search(content)
    outbound_url = shop_m.group(1) if shop_m else None
    if outbound_url is None:
        flags.append("no <a class=\"shop\"> link found — retailer/currency could not be determined")

    retailer = classify_retailer(outbound_url) if outbound_url else None
    if retailer == "Other":
        flags.append(f"outbound link domain not recognized as Amazon/SHEIN/Awin: {outbound_url}")

    price = None
    currency = None
    currency_source = None
    amount_m = IMG_META_AMOUNT_RE.search(content)
    if amount_m and amount_m.group(1):
        try:
            price = float(amount_m.group(1))
        except ValueError:
            flags.append(f"product:price:amount present but not a number: {amount_m.group(1)!r}")

    if retailer == "Amazon":
        if price is not None and outbound_url:
            currency, reason = amazon_currency(outbound_url)
            if currency is None:
                currency_source = None
                flags.append(f"Amazon price found but currency undetermined: {reason}")
            else:
                currency_source = reason
        elif price is None:
            flags.append("Amazon product shows no price on its own page (expected — compliance "
                         "template hides it); price/currency left null")
    elif retailer in ("SHEIN", "Awin"):
        currency_m = IMG_META_CURRENCY_RE.search(content)
        if currency_m and currency_m.group(1):
            currency = currency_m.group(1)
            currency_source = "meta tag"
        elif price is not None:
            flags.append("price found but no product:price:currency meta tag — currency left null")
    elif retailer is None:
        pass  # already flagged above
    else:
        flags.append(f"retailer '{retailer}' not one of Amazon/SHEIN/Awin — currency not attempted")

    img_m = IMG_TAG_RE.search(content)
    image_pending = True
    image = None
    if img_m:
        src_val = img_m.group(1)
        img_path = os.path.join(os.path.dirname(abs_path), urllib.parse.unquote(src_val).replace("/", os.sep))
        if os.path.isfile(img_path):
            image = f"{source}/{theme}/{campaign}/{slug}/{src_val}"
            image_pending = False
        else:
            flags.append(f"<img> present but file missing on disk: {src_val}")
    else:
        flags.append("no <img> tag found on detail page")

    record = {
        "id": f"{theme}/{campaign}/{slug}",
        "slug": slug,
        "name": name,
        "item_type": None,
        "price": price,
        "currency": currency,
        "currency_source": currency_source,
        "retailer": retailer,
        "outbound_url": outbound_url,
        "image": image,
        "image_pending": image_pending,
        "detail_page_url": rel_path,
        "campaign": campaign,
        "theme": theme,
        "source": source,
        "data_new": None,
        "discount_percent": None,
        "thumbnail": None,
    }

    if record["item_type"] is None:
        flags.append("item_type has no source outside human judgment — needs manual classification")
    if record["data_new"] is None:
        flags.append("data_new needs a human decision (is this part of this week's batch?)")

    return record, flags


def generate_thumbnail(image_rel):
    """image_rel is repo-root-relative, e.g. outfits/x/y/z/z.jpg. Returns
    the thumbnail's repo-root-relative path, or None if the source image
    doesn't exist."""
    decoded = urllib.parse.unquote(image_rel)
    src_path = os.path.join(REPO, decoded.replace("/", os.sep))
    if not os.path.isfile(src_path):
        return None
    root, ext = os.path.splitext(image_rel)
    thumb_rel = f"{root}-424{ext}"
    decoded_thumb = urllib.parse.unquote(thumb_rel)
    thumb_path = os.path.join(REPO, decoded_thumb.replace("/", os.sep))

    with Image.open(src_path) as im:
        w, h = im.size
        if w <= THUMB_TARGET_WIDTH:
            shutil.copyfile(src_path, thumb_path)
        else:
            im = im.convert("RGB")
            new_h = round(h * THUMB_TARGET_WIDTH / w)
            im.resize((THUMB_TARGET_WIDTH, new_h), Image.LANCZOS).save(
                thumb_path, "JPEG", quality=THUMB_QUALITY
            )
    return thumb_rel


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--append", action="store_true",
                         help="Append missing records to products.json (default: report only)")
    args = parser.parse_args()

    products = load_products()
    by_detail_url = {p["detail_page_url"]: p for p in products}

    fs_pages = set(find_detail_pages())
    catalog_pages = set(by_detail_url.keys())

    missing_from_catalog = sorted(fs_pages - catalog_pages)
    orphaned_records = sorted(catalog_pages - fs_pages)

    missing_thumbnails = []
    for p in products:
        if p["image_pending"]:
            continue
        if not p.get("thumbnail"):
            missing_thumbnails.append((p["id"], "no thumbnail field set"))
            continue
        thumb_path = os.path.join(REPO, urllib.parse.unquote(p["thumbnail"]).replace("/", os.sep))
        if not os.path.isfile(thumb_path):
            missing_thumbnails.append((p["id"], p["thumbnail"]))

    print("=== sync_catalog.py report ===\n")
    print(f"Detail pages scanned on disk: {len(fs_pages)}")
    print(f"Records in products.json: {len(products)}\n")

    print(f"1. Detail pages with NO products.json record: {len(missing_from_catalog)}")
    for rel in missing_from_catalog:
        print(f"   {rel}")
    print()

    print(f"2. products.json records whose detail page no longer exists on disk: {len(orphaned_records)}")
    for rel in orphaned_records:
        p = by_detail_url[rel]
        print(f"   {p['id']} -> {rel}")
    print()

    print(f"3. products.json records with a missing thumbnail file: {len(missing_thumbnails)}")
    for pid, thumb in missing_thumbnails:
        print(f"   {pid} -> {thumb}")
    print()

    if not missing_from_catalog and not orphaned_records and not missing_thumbnails:
        print("Clean — every detail page on disk has a catalog record, every catalog record's "
              "detail page and thumbnail exist.\n")

    if not args.append:
        if missing_from_catalog:
            print("Run with --append to add the missing records (item_type and data_new will "
                  "still need manual review afterward — see per-record flags).")
        return

    if not missing_from_catalog:
        print("Nothing to append.")
        return

    print("\n=== Appending ===\n")
    appended = 0
    for rel in missing_from_catalog:
        record, flags = build_record(rel)
        if record["image"]:
            thumb = generate_thumbnail(record["image"])
            if thumb:
                record["thumbnail"] = thumb
            else:
                flags.append("thumbnail generation failed — source image missing")
        products.append(record)
        appended += 1
        print(f"+ {record['id']}")
        for fl in flags:
            print(f"    FLAG: {fl}")

    save_products(products)
    print(f"\nAppended {appended} record(s). Total products.json entries: {len(products)}")
    print("Review the FLAG lines above before this batch is considered done — "
          "item_type and data_new need a human decision on every new record.")


if __name__ == "__main__":
    main()
