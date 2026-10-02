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
  3. products.json records whose thumbnail or thumbnail_webp file is
     missing on disk (or whose thumbnail_webp field isn't set).
  4. Product detail pages whose schema.org JSON-LD block is missing, stale,
     or present where it shouldn't be (see add_product_schema.py; run it
     to fix whatever this flags).
  5. sitemap.xml drift: pages (from products.json and the outfits/ and
     videos/ walk) missing from sitemap.xml, sitemap.xml entries whose
     page no longer exists on disk, and entries that shouldn't be there
     (e.g. a page that became a redirect). See write_sitemap.py; run it
     to fix whatever this flags.
  6. Google Analytics and consent: pages whose consent-gated gtag /
     affiliate_click block or site footer (privacy link, "Cookie
     settings", affiliate disclosure) is missing, stale, or present where
     it shouldn't be; a missing privacy/index.html; any page loading
     googletagmanager.com outside the managed block (an ungated tag that
     would ignore the visitor's choice); and product detail pages with no
     outbound .shop link for the click handler to catch. See
     add_analytics.py; run it to fix whatever this flags (except an
     ungated tag, which has to be removed by hand).
  7. Open "PHOTO NEEDED" comments: every .html file (and line) carrying
     one. These mark campaign-level photo problems, like a campaign whose
     outfit-preview.jpg is wrong, that no products.json field tracks.
     No script can fix them (someone has to source a photo), so they
     don't block the "Clean" line for items 1-6, but the summary line
     names them on every run until the comment is removed.
  8. <picture> WebP sources on any page whose srcset doesn't resolve to a
     file (URL-decoded, relative to the page), contains an unencoded space,
     or shows a different picture than the <img> JPEG beside it (e.g. a
     replaced photo whose WebP wasn't regenerated). Unlike a slow image, a
     missing WebP <source> is a broken image in every WebP-capable browser:
     it never falls back to the <img> JPEG. Item 3 applies the same
     missing/mismatch checks to products.json's thumbnail_webp.
  9. Favicons: pages whose favicon / apple-touch-icon block is missing or
     stale, and icon files missing from assets/icons/. See
     add_favicons.py; run it to fix the pages.

WebP (--fill-webp):
  Category-page tiles and the products/ grid serve each -424 thumbnail as a
  <picture> with a same-named .webp <source> and the JPEG <img> as fallback.
  --fill-webp generates any WebP that items 3 and 8 report missing (from
  the full-size original, 424 wide, quality 80, never upscaled) and sets
  thumbnail_webp on the records. --append does the same for new records.
  Hero banners, detail-page photos and og:image/twitter:image stay JPEG.

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
      the rest of the catalog (never upscaled), plus its WebP sibling.
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

from PIL import Image, ImageChops, ImageStat

import add_product_schema
import write_sitemap
import add_analytics
import add_favicons

REPO = os.path.dirname(os.path.abspath(__file__))
PRODUCTS_JSON = os.path.join(REPO, "products.json")
THUMB_TARGET_WIDTH = 424
THUMB_QUALITY = 85
# WebP's quality scale isn't comparable to JPEG's; 80 measured ~46% smaller
# than the quality-85 JPEG thumbnails across the catalog with no visible loss.
WEBP_QUALITY = 80
WEBP_MATCH_THRESHOLD = 15  # see webp_mismatch()

IMG_META_AMOUNT_RE = re.compile(r'<meta property="product:price:amount" content="([^"]*)"')
IMG_META_CURRENCY_RE = re.compile(r'<meta property="product:price:currency" content="([^"]*)"')
SHOP_LINK_RE = re.compile(r'<a class="shop" href="([^"]+)"')
H1_RE = re.compile(r'<h1>(.*?)</h1>', re.DOTALL)
IMG_TAG_RE = re.compile(r'<img src="([^"]+)"')
# (webp srcset, fallback <img> src) for each <picture>
WEBP_PICTURE_RE = re.compile(r'<source type="image/webp" srcset="([^"]*)">\s*<img[^>]*?\ssrc="([^"]*)"')


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
        "thumbnail_webp": None,
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


def webp_rel_for(thumb_rel):
    """x/y-424.jpg -> x/y-424.webp. Keeps the input's URL encoding (products.json
    and the pages store URL-encoded paths, e.g. Darnold%20Shirt-424.jpg)."""
    return os.path.splitext(thumb_rel)[0] + ".webp"


def _abs(rel):
    return os.path.join(REPO, urllib.parse.unquote(rel).replace("/", os.sep))


def _mean_diff(a, b):
    """Mean per-channel pixel difference (0-255) between two same-size RGB images."""
    return sum(ImageStat.Stat(ImageChops.difference(a, b)).mean) / 3


def webp_mismatch(webp_abs, jpeg_abs):
    """None if the WebP shows the same picture as its JPEG, else why not.
    Same-picture pairs measured at most ~5 mean difference across the catalog
    (encoder noise); two different photos measure ~60+."""
    with Image.open(webp_abs) as w, Image.open(jpeg_abs) as j:
        if w.size != j.size:
            return f"doesn't match its JPEG ({w.width}x{w.height} vs {j.width}x{j.height})"
        d = _mean_diff(w.convert("RGB"), j.convert("RGB"))
    return f"doesn't match its JPEG (pixel difference {d:.0f})" if d > WEBP_MATCH_THRESHOLD else None


def generate_webp(thumb_rel):
    """Writes the WebP sibling of a -424 thumbnail and returns its
    repo-root-relative path, or None if the -424 JPEG doesn't exist.

    Encoded from the full-size original (x/y.jpg for x/y-424.jpg), resized to
    424 wide the same way generate_thumbnail() does and never upscaled, so it
    isn't a re-compression of the JPEG thumbnail. But only when that resize
    reproduces the JPEG thumbnail: some -424 files are deliberately not a
    plain resize (gameday-july24's is a close-up crop so its tile differs
    from gameday-jaguars-july30's), and a WebP built from the original would
    silently swap in the other picture for every WebP-capable browser. Those
    are encoded from the -424 JPEG itself."""
    thumb_abs = _abs(thumb_rel)
    if not os.path.isfile(thumb_abs):
        return None
    root, ext = os.path.splitext(thumb_rel)
    original_abs = _abs(re.sub(r"-424$", "", root) + ext)
    with Image.open(thumb_abs) as t:
        thumb = t.convert("RGB")
    im = thumb
    if os.path.isfile(original_abs):
        with Image.open(original_abs) as o:
            o = o.convert("RGB")
            if o.width > THUMB_TARGET_WIDTH:
                o = o.resize((THUMB_TARGET_WIDTH, round(o.height * THUMB_TARGET_WIDTH / o.width)),
                             Image.LANCZOS)
        if o.size == thumb.size and _mean_diff(o, thumb) <= WEBP_MATCH_THRESHOLD:
            im = o
    webp_rel = webp_rel_for(thumb_rel)
    im.save(_abs(webp_rel), "WEBP", quality=WEBP_QUALITY, method=6)
    return webp_rel


def webp_source_issues():
    """Every <source type="image/webp"> on a page must resolve to a file. A
    browser that supports WebP uses the <source> and never falls back to the
    <img> JPEG when it 404s, so a missing file is a broken image, not a
    slower one. The srcset value is resolved the way a browser would:
    relative to the page, URL-decoded. A literal space (not %20) is flagged
    separately: srcset splits candidates on whitespace, so the part after the
    space is read as a size descriptor and the URL is wrong. The WebP must
    also show the same picture as the <img> fallback beside it, or a photo
    replaced without regenerating its WebP keeps showing the old one."""
    issues = []
    for rel in add_analytics.all_html():
        page = os.path.join(REPO, rel.replace("/", os.sep))
        with open(page, encoding="utf-8", errors="replace") as f:
            content = f.read()
        for src, fallback in WEBP_PICTURE_RE.findall(content):
            if re.search(r"\s", src.strip()):
                issues.append((rel, src, "unencoded whitespace in srcset (use %20)"))
                continue
            target = os.path.join(os.path.dirname(page), urllib.parse.unquote(src).replace("/", os.sep))
            if not os.path.isfile(target):
                issues.append((rel, src, "file missing"))
                continue
            jpeg = os.path.join(os.path.dirname(page), urllib.parse.unquote(fallback).replace("/", os.sep))
            if os.path.isfile(jpeg):
                why = webp_mismatch(target, jpeg)
                if why:
                    issues.append((rel, src, why))
    return issues


def fill_webp(products):
    """--fill-webp: give every record with a thumbnail a WebP sibling and a
    thumbnail_webp field, and (re)generate the file behind any page's
    <source> that is missing or no longer matches its <img> JPEG."""
    print("=== Filling WebP thumbnails ===\n")
    made = 0
    for p in products:
        if p["image_pending"] or not p.get("thumbnail"):
            continue
        webp = p.get("thumbnail_webp")
        if (webp and os.path.isfile(_abs(webp)) and os.path.isfile(_abs(p["thumbnail"]))
                and not webp_mismatch(_abs(webp), _abs(p["thumbnail"]))):
            continue
        webp = generate_webp(p["thumbnail"])
        if webp:
            p["thumbnail_webp"] = webp
            made += 1
        else:
            print(f"   could not generate WebP for {p['id']} (no source image)")
    if made:
        save_products(products)
    print(f"products.json records: {made} WebP thumbnail(s) generated")

    pages = 0
    for rel, src, why in webp_source_issues():
        if why.startswith("unencoded whitespace"):
            continue
        page_dir = os.path.dirname(rel)
        stem = os.path.splitext(src)[0]
        for ext in (".jpg", ".jpeg"):
            thumb_rel = f"{page_dir}/{stem}{ext}"
            if os.path.isfile(_abs(thumb_rel)):
                generate_webp(thumb_rel)
                pages += 1
                break
        else:
            print(f"   {rel}: no -424 JPEG next to {src} to build it from")
    print(f"page <source> files: {pages} WebP thumbnail(s) generated\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--append", action="store_true",
                         help="Append missing records to products.json (default: report only)")
    parser.add_argument("--fill-webp", action="store_true",
                         help="Generate missing WebP thumbnails for products.json records and "
                              "set their thumbnail_webp field (default: report only)")
    args = parser.parse_args()

    products = load_products()

    if args.fill_webp:
        fill_webp(products)

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
        if not p.get("thumbnail_webp"):
            missing_thumbnails.append((p["id"], "no thumbnail_webp field set"))
        elif not os.path.isfile(_abs(p["thumbnail_webp"])):
            missing_thumbnails.append((p["id"], p["thumbnail_webp"]))
        elif os.path.isfile(thumb_path):
            why = webp_mismatch(_abs(p["thumbnail_webp"]), thumb_path)
            if why:
                missing_thumbnails.append((p["id"], f"{p['thumbnail_webp']} {why}"))

    webp_issues = webp_source_issues()
    favicon_issues = add_favicons.audit()
    favicon_issues += [(path, "icon file missing") for path in add_favicons.missing_icons()]

    schema_issues = []
    for p in products:
        page = os.path.join(REPO, p["detail_page_url"].replace("/", os.sep))
        if not os.path.isfile(page):
            continue  # already reported in (2)
        st = add_product_schema.status(p, add_product_schema.read_page(page))
        if st != "ok":
            schema_issues.append((p["id"], st))

    sitemap_issues = []
    in_sitemap = write_sitemap.sitemap_urls()
    if in_sitemap is None:
        sitemap_issues.append(("sitemap.xml does not exist", ""))
    else:
        expected = [u for u, _ in write_sitemap.expected_urls()]
        expected_set, sitemap_set = set(expected), set(in_sitemap)
        for url in expected:
            if url not in sitemap_set:
                sitemap_issues.append(("missing from sitemap.xml", url))
        for url in in_sitemap:
            if url in expected_set:
                continue
            page = write_sitemap.page_for(url)
            if page is None or not os.path.isfile(os.path.join(REPO, page.replace("/", os.sep))):
                sitemap_issues.append(("in sitemap.xml but page no longer exists", url))
            else:
                sitemap_issues.append(("in sitemap.xml but shouldn't be (redirect or excluded page)", url))
        if not sitemap_issues and write_sitemap.is_stale():
            sitemap_issues.append(("sitemap.xml has out-of-date <lastmod> dates", ""))

    analytics_issues = list(add_analytics.audit())
    if not os.path.isfile(os.path.join(REPO, add_analytics.PRIVACY_PAGE.replace("/", os.sep))):
        analytics_issues.append((add_analytics.PRIVACY_PAGE, "privacy page missing; banner and footer link to it"))
    analytics_issues += [(rel, "googletagmanager.com loaded outside the consent gate; remove by hand")
                         for rel in add_analytics.ungated_tags()]
    analytics_issues += [(rel, "no outbound .shop link for the click handler")
                         for rel in add_analytics.untracked_links()]

    photo_needed = []
    for rel in add_analytics.all_html():
        with open(os.path.join(REPO, rel.replace("/", os.sep)), encoding="utf-8", errors="replace") as f:
            for lineno, line in enumerate(f, 1):
                if "PHOTO NEEDED" in line:
                    photo_needed.append((rel, lineno))

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

    print(f"3. products.json records with a missing thumbnail or WebP thumbnail file: "
          f"{len(missing_thumbnails)}")
    for pid, thumb in missing_thumbnails:
        print(f"   {pid} -> {thumb}")
    if missing_thumbnails:
        print("   Run: python sync_catalog.py --fill-webp  (fixes WebP entries only)")
    print()

    print(f"4. Detail pages with a missing/stale product schema block: {len(schema_issues)}")
    for pid, st in schema_issues:
        print(f"   {pid} ({st})")
    if schema_issues:
        print("   Run: python add_product_schema.py")
    print()

    print(f"5. sitemap.xml entries missing, stale, or unwanted: {len(sitemap_issues)}")
    for why, url in sitemap_issues:
        print(f"   {why}: {url}" if url else f"   {why}")
    if sitemap_issues:
        print("   Run: python write_sitemap.py")
    print()

    print(f"6. Pages with a missing/stale consent-gated analytics block or site footer, "
          f"ungated Google tag, or untracked .shop link: "
          f"{len(analytics_issues)}")
    for rel, why in analytics_issues:
        print(f"   {rel} ({why})")
    if analytics_issues:
        print("   Run: python add_analytics.py")
    print()

    print(f"7. Open PHOTO NEEDED comments (a photo has to be sourced by hand): {len(photo_needed)}")
    for rel, lineno in photo_needed:
        print(f"   {rel}:{lineno}")
    print()

    print(f"8. <picture> WebP sources that won't load or don't match their JPEG "
          f"(browsers don't fall back to the JPEG): {len(webp_issues)}")
    for rel, src, why in webp_issues:
        print(f"   {rel}: {src} ({why})")
    if any(not why.startswith("unencoded whitespace") for _, _, why in webp_issues):
        print("   Run: python sync_catalog.py --fill-webp  (regenerates missing or mismatched "
              "files; fix unencoded spaces by hand)")
    print()

    print(f"9. Pages with a missing/stale favicon block, or missing icon files: {len(favicon_issues)}")
    for rel, why in favicon_issues:
        print(f"   {rel} ({why})")
    if any(why != "icon file missing" for _, why in favicon_issues):
        print("   Run: python add_favicons.py")
    print()

    if (not missing_from_catalog and not orphaned_records and not missing_thumbnails
            and not schema_issues and not sitemap_issues and not analytics_issues
            and not webp_issues and not favicon_issues):
        print("Clean — every detail page on disk has a catalog record, every catalog record's "
              "detail page, thumbnail and WebP thumbnail exist, every schema block is current, "
              "sitemap.xml matches the pages on disk, every page has current consent-gated "
              "analytics tracking and site footer, every <picture> WebP source loads, and every "
              "page has a current favicon block.")
        if photo_needed:
            files = len({rel for rel, _ in photo_needed})
            print(f"Still open: {len(photo_needed)} PHOTO NEEDED comment(s) in {files} file(s) "
                  "— see item 7.")
        print()

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
                record["thumbnail_webp"] = generate_webp(thumb)
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
