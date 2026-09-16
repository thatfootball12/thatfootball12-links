#!/usr/bin/env python3
"""
Reads parsed_products.csv (from parse_shein.py) and adds slot/color/register
columns by matching keywords in the product title.

Usage in Claude Code:
    "Run classify.py"

This is intentionally keyword-based, not ML — SHEIN titles are already
keyword-dense (garment type, color, season, style), so a match table gets
most of the way there. It WILL be wrong sometimes; that's expected. Wrong
guesses get corrected by hand in the CSV before outfit-building runs.
"""

import csv

# Order matters: more specific terms checked first so e.g. "cargo pants"
# doesn't get missed by a looser "pants" rule elsewhere.
SLOT_RULES = [
    ("outer", ["jacket", "coat", "parka", "windbreaker", "puffer", "overshirt", "shacket"]),
    ("mid", ["sweater", "hoodie", "sweatshirt", "cardigan", "flannel", "pullover", "fleece"]),
    ("base", ["t-shirt", "tshirt", "tee", "polo", "shirt", "tank"]),
    ("footwear", ["shoes", "sneakers", "boots", "sandals", "slippers", "loafers"]),
    ("bottom", ["pants", "trousers", "jeans", "shorts", "chinos", "joggers"]),
    ("accessory", ["hat", "cap", "beanie", "belt", "bag", "watch", "sunglasses", "scarf", "wallet"]),
]

COLOR_WORDS = [
    "black", "white", "grey", "gray", "navy", "blue", "green", "brown",
    "beige", "khaki", "olive", "red", "burgundy", "tan", "cream", "orange",
    "yellow", "purple", "pink",
]

REGISTER_RULES = [
    ("athleisure", ["gym", "sport", "athletic", "training", "compression", "athleisure"]),
    ("streetwear", ["street", "graphic", "oversize", "baggy", "urban"]),
    ("business_casual", ["business", "office", "smart", "dress"]),
    ("gameday", ["fan", "jersey", "team", "nfl", "football"]),
    ("casual", ["casual", "everyday", "commuter", "basic"]),  # fallback-ish, checked last
]


def classify_slot(title):
    t = title.lower()
    for slot, keywords in SLOT_RULES:
        if any(kw in t for kw in keywords):
            return slot
    return "UNCLASSIFIED"


def classify_color(title):
    t = title.lower()
    found = [c for c in COLOR_WORDS if c in t]
    if not found:
        return ""
    # dedupe gray/grey
    found = list(dict.fromkeys("grey" if c == "gray" else c for c in found))
    return "+".join(found)


def classify_register(title):
    t = title.lower()
    for register, keywords in REGISTER_RULES:
        if any(kw in t for kw in keywords):
            return register
    return "unspecified"


def needs_image_check(title):
    """SHEIN's og:image sometimes shows a different color variant than the
    one named in the title (e.g. title says 'White', photo shows green).
    The script has no way to verify the photo itself, so any title naming
    a specific color gets flagged for a manual look before publishing."""
    t = title.lower()
    return any(c in t for c in COLOR_WORDS)


def main():
    with open("parsed_products.csv", "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        raise SystemExit("parsed_products.csv is empty — run parse_shein.py first.")

    fieldnames = list(rows[0].keys()) + ["slot", "color", "register", "verify_image"]

    for row in rows:
        row["slot"] = classify_slot(row["title"])
        row["color"] = classify_color(row["title"])
        row["register"] = classify_register(row["title"])
        row["verify_image"] = "YES - check color" if needs_image_check(row["title"]) else ""

    out_path = "classified_products.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Classified {len(rows)} products -> {out_path}\n")
    unclassified = 0
    needs_check = 0
    for r in rows:
        flags = []
        if r["slot"] == "UNCLASSIFIED":
            flags.append("NO SLOT")
            unclassified += 1
        if r["verify_image"]:
            flags.append("VERIFY IMAGE")
            needs_check += 1
        flag_str = f"  <- {', '.join(flags)}" if flags else ""
        print(f"  [{r['slot']:<10}] [{r['color'] or '?':<12}] [{r['register']:<16}] {r['title'][:50]}{flag_str}")

    if unclassified:
        print(f"\n{unclassified} item(s) need a manual slot — edit classified_products.csv directly.")
    if needs_check:
        print(f"{needs_check} item(s) name a color in the title — open the image URL and confirm "
              f"it matches before this goes into Bulk Create. SHEIN's og:image sometimes shows "
              f"a different variant than the one named.")


if __name__ == "__main__":
    main()
