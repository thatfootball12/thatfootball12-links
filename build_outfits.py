#!/usr/bin/env python3
"""
Reads classified_products.csv and proposes outfit groupings by filling
slots: base (required), bottom (required), one of outer/mid (preferred),
footwear (preferred), accessory (optional).

Usage in Claude Code:
    "Run build_outfits.py"

This does NOT try to be clever about color matching beyond a basic clash
check — SHEIN titles often don't name a color at all (see the 'color'
column), so there frequently isn't enough signal to do real palette
matching. It surfaces its reasoning so you can override in the CSV.

Output: outfits.csv, one row per proposed outfit, listing which product
row (by title) fills each slot, plus a total price and any items left
unused.
"""

import csv
import itertools

# Colors that read as visually incompatible together in one outfit.
# Deliberately short and conservative — most combos are fine, this only
# catches the obvious clashes worth a second look.
CLASH_PAIRS = {
    frozenset(["red", "green"]),
    frozenset(["orange", "pink"]),
    frozenset(["purple", "orange"]),
}

# Which registers can reasonably appear together in one outfit.
# "casual" and "unspecified" are treated as neutral — they can pair with
# anything, since most SHEIN titles that just say "casual" don't carry a
# strong occasion signal either way.
NEUTRAL_REGISTERS = {"casual", "unspecified"}

COMPATIBLE_REGISTERS = {
    frozenset(["business_casual"]),
    frozenset(["athleisure"]),
    frozenset(["streetwear"]),
    frozenset(["gameday"]),
    frozenset(["business_casual", "streetwear"]),  # old-money/streetwear crossover is real
}


def load_products():
    with open("classified_products.csv", "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def colors_clash(color_field_a, color_field_b):
    colors_a = set(color_field_a.split("+")) if color_field_a else set()
    colors_b = set(color_field_b.split("+")) if color_field_b else set()
    for ca in colors_a:
        for cb in colors_b:
            if frozenset([ca, cb]) in CLASH_PAIRS:
                return True
    return False


def registers_compatible(reg_a, reg_b):
    """Two items can share an outfit if either is neutral, they match
    exactly, or they're an explicitly allowed crossover pair."""
    if reg_a in NEUTRAL_REGISTERS or reg_b in NEUTRAL_REGISTERS:
        return True
    if reg_a == reg_b:
        return True
    return frozenset([reg_a, reg_b]) in COMPATIBLE_REGISTERS


def outfit_register(items):
    """The non-neutral register driving this outfit, if any — used for
    naming/labeling. Returns 'casual' if every item is neutral."""
    specific = [i["register"] for i in items if i["register"] not in NEUTRAL_REGISTERS]
    return specific[0] if specific else "casual"


def build_outfits(products):
    by_slot = {}
    for p in products:
        by_slot.setdefault(p["slot"], []).append(p)

    bases = by_slot.get("base", [])
    bottoms = by_slot.get("bottom", [])
    layers = by_slot.get("outer", []) + by_slot.get("mid", [])
    footwear = by_slot.get("footwear", [])
    accessories = by_slot.get("accessory", [])

    if not bases or not bottoms:
        return [], "Need at least one 'base' and one 'bottom' item to build any outfit."

    outfits = []
    used_pairs = set()  # (base title, bottom title) — avoid the same core twice
    used_bases = set()
    used_bottoms = set()

    for base, bottom in itertools.product(bases, bottoms):
        key = (base["title"], bottom["title"])
        if key in used_pairs:
            continue
        # Don't let one item anchor every outfit — each base and each
        # bottom is used at most once across the whole batch, so 5
        # outfits mean 5 different core looks, not one tee styled 5 ways.
        if base["title"] in used_bases or bottom["title"] in used_bottoms:
            continue
        if colors_clash(base["color"], bottom["color"]):
            continue
        if not registers_compatible(base["register"], bottom["register"]):
            continue

        core = [base, bottom]

        # Layer, footwear, accessory are optional add-ons, not required
        # slots. Only add one if it's register-compatible with the core
        # AND hasn't already been used in a previous outfit — reusing the
        # one hat/jacket across every outfit is worse than leaving it off.
        def pick_addon(pool, used_titles):
            for item in pool:
                if item["title"] in used_titles:
                    continue
                if not registers_compatible(item["register"], outfit_register(core)):
                    continue
                if any(colors_clash(item["color"], c["color"]) for c in core):
                    continue
                return item
            return None

        used_addons = set()
        for o in outfits:
            for slot_name in ("layer", "footwear", "accessory"):
                if o.get(f"{slot_name}_title"):
                    used_addons.add(o[f"{slot_name}_title"])

        layer = pick_addon(layers, used_addons)
        shoe = pick_addon(footwear, used_addons | ({layer["title"]} if layer else set()))
        acc = pick_addon(accessories, used_addons | ({layer["title"]} if layer else set())
                          | ({shoe["title"]} if shoe else set()))

        items = core + [x for x in [layer, shoe, acc] if x]
        total = sum(float(x["price"]) for x in items)

        outfits.append({
            "outfit_id": f"outfit_{len(outfits) + 1}",
            "register": outfit_register(items),
            "base": base["title"],
            "bottom": bottom["title"],
            "layer": layer["title"] if layer else "",
            "layer_title": layer["title"] if layer else "",
            "footwear": shoe["title"] if shoe else "",
            "footwear_title": shoe["title"] if shoe else "",
            "accessory": acc["title"] if acc else "",
            "accessory_title": acc["title"] if acc else "",
            "total_price": f"{total:.2f}",
            "missing_slots": ", ".join(
                s for s, present in
                [("layer", bool(layer)), ("footwear", bool(shoe)), ("accessory", bool(acc))]
                if not present
            ),
        })
        used_pairs.add(key)
        used_bases.add(base["title"])
        used_bottoms.add(bottom["title"])

    return outfits, None


def main():
    products = load_products()
    if not products:
        raise SystemExit("classified_products.csv is empty — run classify.py first.")

    outfits, error = build_outfits(products)
    if error:
        print(error)
        return

    fieldnames = ["outfit_id", "register", "base", "bottom", "layer",
                  "footwear", "accessory", "total_price", "missing_slots"]

    # Sort so outfits with the most filled slots (fullest looks) come
    # first — those are the ones worth reviewing before the thinner ones.
    outfits.sort(key=lambda o: len(o["missing_slots"]))

    # Cap output: a real weekly batch should be 2-5 solid outfits, not
    # every mathematically valid base x bottom combination.
    MAX_OUTFITS = 5
    kept = outfits[:MAX_OUTFITS]
    dropped = len(outfits) - len(kept)

    with open("outfits.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(kept)

    print(f"Built {len(kept)} outfit(s) -> outfits.csv"
          f"{f'  ({dropped} more valid combos not shown — raise MAX_OUTFITS to see them)' if dropped else ''}\n")
    for o in kept:
        print(f"--- {o['outfit_id']}  [{o['register']}]  (${o['total_price']}) ---")
        print(f"  base:      {o['base'][:60]}")
        print(f"  bottom:    {o['bottom'][:60]}")
        if o["layer"]:
            print(f"  layer:     {o['layer'][:60]}")
        if o["footwear"]:
            print(f"  footwear:  {o['footwear'][:60]}")
        if o["accessory"]:
            print(f"  accessory: {o['accessory'][:60]}")
        if o["missing_slots"]:
            print(f"  (no {o['missing_slots']} available for this pairing)")
        print()

    print("Review each outfit before building images — this is a mechanical "
          "pairing by occasion/register, not a styling judgment. Reshuffle "
          "or drop items in outfits.csv as needed.")


if __name__ == "__main__":
    main()
