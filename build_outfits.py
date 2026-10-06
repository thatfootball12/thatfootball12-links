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
import re

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


# NFL teams by nickname, for keeping gameday outfits to one team. Only
# gameday-register items are checked, so a SHEIN "Eagle Print Shirt" or a
# phone "Chargers" listing never gets read as team gear.
NFL_TEAMS = [
    "49ers", "bears", "bengals", "bills", "broncos", "browns", "buccaneers",
    "cardinals", "chargers", "chiefs", "colts", "commanders", "cowboys",
    "dolphins", "eagles", "falcons", "giants", "jaguars", "jets", "lions",
    "packers", "panthers", "patriots", "raiders", "rams", "ravens", "saints",
    "seahawks", "steelers", "texans", "titans", "vikings",
]

# Titles that name only a player (or city) and not the team. Hand-maintained:
# add an entry when a batch has a player jersey or tee without the nickname.
TEAM_ALIASES = {
    "kelce": "chiefs",
    "ja'marr chase": "bengals",
    "cincinnati": "bengals",
    "bijan robinson": "falcons",
    "drake maye": "patriots",
    # NHL: not in NFL_TEAMS, so the team has to come from an alias.
    "leafs": "maple leafs",
    "matthews": "maple leafs",
}


def item_team(item):
    """The NFL team an item belongs to, or None if it's team-neutral."""
    if item["register"] != "gameday":
        return None
    t = item["title"].lower()
    for team in NFL_TEAMS:
        if re.search(rf"\b{re.escape(team)}\b", t):
            return team
    for alias, team in TEAM_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", t):
            return team
    return None


def outfit_team(items):
    """The single team these items commit to, None if all are neutral, or
    False if they already mix two teams."""
    teams = {item_team(i) for i in items} - {None}
    if len(teams) > 1:
        return False
    return teams.pop() if teams else None


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
    seen_combos = set()  # full (base, bottom, layer, footwear, accessory) tuples
    usage = {}           # title -> times used so far, for preferring fresh items
    used_layers = set()

    def prefer_fresh(pool):
        # Stable sort, least-used first (file order breaks ties). Reuse is
        # allowed, but a batch where every outfit shares one pair of jeans
        # isn't useful when alternatives exist.
        return sorted(pool, key=lambda i: usage.get(i["title"], 0))

    # Each base anchors at most one outfit, so every outfit is a distinct
    # core look. Bottoms, footwear, and accessories CAN repeat across
    # outfits; layers stay one-per-batch. The only hard rule is that the
    # exact same full combination never appears twice.
    for base in bases:
        candidates = [
            bottom for bottom in prefer_fresh(bottoms)
            if not colors_clash(base["color"], bottom["color"])
            and registers_compatible(base["register"], bottom["register"])
            and outfit_team([base, bottom]) is not False
        ]

        for bottom in candidates:
            core = [base, bottom]

            # Layer, footwear, accessory are optional add-ons, not required
            # slots. Only add one if it's register-compatible with the core.
            # For gameday outfits, try gameday add-ons first (team jackets,
            # beanies, socks) so a fan tee doesn't end up with only generic
            # pieces just because those come earlier in the CSV.
            #
            # Team rule: an add-on from the outfit's team comes first, then
            # team-neutral items. Gear from a different team is never used,
            # even if that leaves the slot empty.
            def pick_addon(pool, exclude_titles, chosen):
                team = outfit_team(chosen)
                gameday = outfit_register(core) == "gameday"
                pool = sorted(pool, key=lambda i: (
                    not (team and item_team(i) == team),
                    not (gameday and i["register"] == "gameday"),
                ))
                for item in pool:
                    if item["title"] in exclude_titles:
                        continue
                    if outfit_team(chosen + [item]) is False:
                        continue
                    if not registers_compatible(item["register"], outfit_register(core)):
                        continue
                    if any(colors_clash(item["color"], c["color"]) for c in core):
                        continue
                    return item
                return None

            chosen = list(core)
            layer = pick_addon([l for l in layers if l["title"] not in used_layers], set(), chosen)
            chosen += [layer] if layer else []
            shoe = pick_addon(prefer_fresh(footwear), set(), chosen)
            chosen += [shoe] if shoe else []
            acc = pick_addon(prefer_fresh(accessories), {x["title"] for x in chosen}, chosen)

            combo = tuple(x["title"] if x else "" for x in (base, bottom, layer, shoe, acc))
            if combo in seen_combos:
                continue

            items = core + [x for x in [layer, shoe, acc] if x]
            total = sum(float(x["price"]) for x in items)

            outfits.append({
                "outfit_id": f"outfit_{len(outfits) + 1}",
                "register": outfit_register(items),
                "base": base["title"],
                "bottom": bottom["title"],
                "layer": layer["title"] if layer else "",
                "footwear": shoe["title"] if shoe else "",
                "accessory": acc["title"] if acc else "",
                "total_price": f"{total:.2f}",
                "missing_slots": ", ".join(
                    s for s, present in
                    [("layer", bool(layer)), ("footwear", bool(shoe)), ("accessory", bool(acc))]
                    if not present
                ),
            })
            seen_combos.add(combo)
            for x in items:
                usage[x["title"]] = usage.get(x["title"], 0) + 1
            if layer:
                used_layers.add(layer["title"])
            break

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

    # Cap output at roughly one weekly batch (14-17 outfits lately), not
    # every mathematically valid base x bottom combination.
    MAX_OUTFITS = 17
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
