#!/usr/bin/env python3
"""
Fills the image_url column in classified_products.csv by visiting each
SHEIN link and reading its og:image meta tag.

Usage in Claude Code:
    "Run fetch_images.py"

Notes:
- SHEIN's og:image is often a small thumbnail (e.g. ..._thumbnail_405x552.jpg).
  This script tries to swap that for a larger size first, and falls back
  to the original thumbnail URL if the larger version doesn't exist.
- Network failures on individual products don't stop the batch — they're
  reported at the end so you know which rows still need an image.
"""

import csv
import re
import time
import urllib.request
import urllib.error

OG_IMAGE_RE = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
# Handles attribute order the other way round too (content before property)
OG_IMAGE_RE_ALT = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
    re.IGNORECASE,
)

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; TF12-ImageFetch/1.0)"}


def fetch_html(url, timeout=15):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def extract_og_image(html):
    m = OG_IMAGE_RE.search(html) or OG_IMAGE_RE_ALT.search(html)
    return m.group(1) if m else None


def upsize_thumbnail(url):
    """SHEIN thumbnail URLs often look like ..._thumbnail_405x552.jpg.
    Try a larger size; the caller falls back to the original if this 404s."""
    return re.sub(r"_thumbnail_\d+x\d+\.jpg", "_thumbnail_900x1200.jpg", url)


def url_exists(url, timeout=10):
    try:
        req = urllib.request.Request(url, headers=HEADERS, method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def get_best_image(product_url):
    html = fetch_html(product_url)
    og_image = extract_og_image(html)
    if not og_image:
        return None

    upsized = upsize_thumbnail(og_image)
    if upsized != og_image and url_exists(upsized):
        return upsized
    return og_image


def main():
    with open("classified_products.csv", "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        fieldnames = list(rows[0].keys()) if rows else []

    if not rows:
        raise SystemExit("classified_products.csv is empty — run classify.py first.")

    failures = []

    for i, row in enumerate(rows, 1):
        if row.get("image_url"):
            print(f"  [{i}] already has an image, skipping")
            continue

        title_preview = row["title"][:50]
        try:
            image_url = get_best_image(row["link"])
            if image_url:
                row["image_url"] = image_url
                print(f"  [{i}] OK   {title_preview}")
            else:
                failures.append(row["title"])
                print(f"  [{i}] FAIL (no og:image found)  {title_preview}")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            failures.append(row["title"])
            print(f"  [{i}] FAIL ({e})  {title_preview}")

        time.sleep(1)  # be polite to SHEIN's servers between requests

    with open("classified_products.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nDone. {len(rows) - len(failures)}/{len(rows)} images fetched.")
    if failures:
        print("These need an image added manually:")
        for t in failures:
            print(f"  - {t[:70]}")


if __name__ == "__main__":
    main()
