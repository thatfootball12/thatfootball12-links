#!/usr/bin/env python3
"""
Parses SHEIN share-button text blobs into structured product rows.

Usage in Claude Code:
    "Run parse_shein.py on batch.txt"

Input format expected (one or more blobs, separated by blank lines):
    🎉Don't miss this hot deal on SHEIN! Save big on this!
    💰Price[CA$28.48]
    🛒<full product title>
    🎁60% OFF COUPON for every New User!
    https://onelink.shein.com/...

Output: a CSV at parsed_products.csv with one row per product.
Image URLs are NOT fetched here — that's a separate step (fetch_images.py)
since it needs to follow the link and may need retries.
"""

import csv
import re
import sys

PRICE_RE = re.compile(r"💰\s*Price\[(CA\$|US\$|\$)?([\d.]+)\]\s*(-(\d+)%)?")
TITLE_RE = re.compile(r"🛒\s*(.+)")
LINK_RE = re.compile(r"https?://onelink\.shein\.com\S+")


def parse_blob(blob):
    """Parse one SHEIN share blob. Returns a dict, or None if it doesn't
    look like a SHEIN blob at all (so callers can skip junk safely)."""
    price_match = PRICE_RE.search(blob)
    title_match = TITLE_RE.search(blob)
    link_match = LINK_RE.search(blob)

    if not (price_match and title_match and link_match):
        return None

    currency = price_match.group(1) or "$"
    price = float(price_match.group(2))
    discount_pct = price_match.group(4)  # None if no "-XX%" shown

    title = title_match.group(1).strip()
    # Title sometimes runs up against the next emoji line on one line;
    # cut it off at the first 🎁 if present.
    title = title.split("🎁")[0].strip()

    link = link_match.group(0)

    return {
        "title": title,
        "price": price,
        "currency": currency.replace("CA$", "CAD").replace("US$", "USD").replace("$", "CAD"),
        "discount_pct": discount_pct or "",
        "link": link,
        "image_url": "",  # filled in later by fetch_images.py
    }


def split_batch(text):
    """Split a pasted batch into individual blobs. SHEIN blobs are
    separated by blank lines in a normal paste, but we fall back to
    splitting on the recurring 🎉 opener in case formatting collapses."""
    chunks = [c.strip() for c in text.split("\n\n") if c.strip()]
    if len(chunks) <= 1 and text.count("🎉") > 1:
        chunks = ["🎉" + c for c in text.split("🎉") if c.strip()]
    return chunks


def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: python3 parse_shein.py <input_file.txt>")

    with open(sys.argv[1], "r", encoding="utf-8") as f:
        text = f.read()

    blobs = split_batch(text)
    rows = []
    skipped = 0
    seen_titles = set()
    duplicates = 0

    for i, blob in enumerate(blobs, 1):
        row = parse_blob(blob)
        if row is None:
            skipped += 1
            print(f"  [skip] blob {i} didn't match expected SHEIN format")
            continue
        # Same product is often shared twice with different affiliate
        # links. Title is the stable identifier here (price/link aren't),
        # so dedupe on it and keep the first occurrence.
        key = row["title"].strip().lower()
        if key in seen_titles:
            duplicates += 1
            print(f"  [dup] blob {i} is a duplicate title, skipping: {row['title'][:60]}")
            continue
        seen_titles.add(key)
        rows.append(row)

    if not rows:
        sys.exit("No valid SHEIN blobs found. Check the input format.")

    out_path = "parsed_products.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nParsed {len(rows)} products ({skipped} skipped, {duplicates} duplicates) -> {out_path}")
    for r in rows:
        print(f"  {r['currency']} {r['price']:.2f}  {r['title'][:60]}")


if __name__ == "__main__":
    main()
