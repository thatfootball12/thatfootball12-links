#!/usr/bin/env python3
"""
Random Outfit Generator support: the Python copy of the slot pools, style
rules and budget check that generator/index.html runs in the browser, all
driven by generator.json (with categories.json for each product's tab and
sub-chip). sync_catalog.py imports audit() for report item 11.

Run directly to see each theme's pool sizes and which budget tiers can
produce an outfit (the page greys out the ones that can't):
    py -3 outfit_generator.py

Keep this file and the matching functions in generator/index.html
(buildPools, ruleBlocks, compatible, feasible, shortCode) in step.
"""

import json
import os
import sys

import categories

REPO = os.path.dirname(os.path.abspath(__file__))
GENERATOR_JSON = os.path.join(REPO, "generator.json")
PRODUCTS_JSON = os.path.join(REPO, "products.json")
MIN_POOL = 5  # below this a slot is reported as thin (warning only)


def load():
    with open(GENERATOR_JSON, encoding="utf-8") as f:
        return json.load(f)


def short_code(pid):
    """7-character base-36 FNV-1a hash of a product id, used in outfit links
    (#theme/budget/code.code.code.code). Same as shortCode() in the page."""
    h = 0x811C9DC5
    for b in pid.encode("utf-8"):
        h ^= b
        h = (h * 0x01000193) & 0xFFFFFFFF
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    out = ""
    while h:
        h, r = divmod(h, 36)
        out = digits[r] + out
    return out.rjust(7, "0")


def matches(cat, patterns):
    return any(cat == p or cat.startswith(p + "/") for p in patterns)


def priced(p):
    return p["retailer"] != "Amazon" and isinstance(p.get("price"), (int, float))


def records(products, cat_cfg, gen):
    """Products the generator may use: placed by categories.json (so not
    hidden), not excluded, not banned by a 'never' rule. Each is
    {"p": product, "cat": "tab/sub" or "tab", "index": n}."""
    never = [pat for r in gen["rules"] if "never" in r for pat in r["never"]]
    out = []
    for i, p in enumerate(products):
        if p["id"] in gen["exclude"]:
            continue
        placed = categories.place(p, cat_cfg)
        if not placed:
            continue
        cat = placed[0] + ("/" + placed[1] if placed[1] else "")
        if matches(cat, never):
            continue
        out.append({"p": p, "cat": cat, "index": i})
    return out


def _dedupe(recs):
    """One record per outbound link (the same product shows up in several
    campaigns): the newest, then earliest in products.json."""
    best = {}
    for r in recs:
        key = r["p"]["outbound_url"] or r["p"]["id"]
        cur = best.get(key)
        if cur is None or (r["p"]["added"], -r["index"]) > (cur["p"]["added"], -cur["index"]):
            best[key] = r
    return sorted(best.values(), key=lambda r: r["index"])


def build_pools(recs, gen, theme_slug):
    """{slot: [record, ...]} for a theme slug, or "any"."""
    themes = {t["slug"]: t for t in gen["themes"]}
    theme = themes.get(theme_slug)
    pools = {}
    for slot, spec in gen["slots"].items():
        if theme is None:
            camps = None  # any campaign
        else:
            camps = set(theme["campaigns"])
            borrow = theme.get("borrow")
            if borrow and slot in borrow["slots"]:
                camps |= set(themes[borrow["from"]]["campaigns"])
        chosen = [r for r in recs
                  if (camps is None or r["p"]["campaign"] in camps) and matches(r["cat"], spec["allow"])]
        if theme is not None and theme.get("fan_gear") and spec.get("fan_gear"):
            chosen += [r for r in recs if matches(r["cat"], spec["fan_gear"])]
        pools[slot] = _dedupe(chosen)
    return pools


def compatible(cats, gen):
    """True if no rule blocks this set of piece categories."""
    for rule in gen["rules"]:
        if "if" not in rule:
            continue
        for i, cat in enumerate(cats):
            if not matches(cat, rule["if"]):
                continue
            others = cats[:i] + cats[i + 1:]
            if "not_with" in rule and any(matches(o, rule["not_with"]) for o in others):
                return False
            if "only_with" in rule and not any(matches(o, rule["only_with"]) for o in others):
                return False
    return True


def feasible(pools, gen, budget):
    """Is there any valid outfit (base slots + one extra) with every item
    priced and the total under budget? Depth-first over price-sorted pools,
    pruned by the cheapest remaining slots."""
    order = gen["base_slots"]
    sorted_pools = {s: sorted([r for r in pools[s] if priced(r["p"])], key=lambda r: r["p"]["price"])
                    for s in pools}
    extra_prices = [sorted_pools[s][0]["p"]["price"] for s in gen["extra_slots"] if sorted_pools[s]]
    if not extra_prices or any(not sorted_pools[s] for s in order):
        return False
    extra_min = min(extra_prices)
    rest_min = [sum(sorted_pools[s][0]["p"]["price"] for s in order[i:]) + extra_min
                for i in range(len(order) + 1)]

    def dfs(i, total, cats):
        if total + rest_min[i] >= budget:
            return False
        if i == len(order):
            for s in gen["extra_slots"]:
                for r in sorted_pools[s]:
                    if total + r["p"]["price"] >= budget:
                        break
                    if compatible(cats + [r["cat"]], gen):
                        return True
            return False
        for r in sorted_pools[order[i]]:
            if total + r["p"]["price"] + rest_min[i + 1] >= budget:
                break
            if compatible(cats + [r["cat"]], gen) and dfs(i + 1, total + r["p"]["price"], cats + [r["cat"]]):
                return True
        return False

    return dfs(0, 0.0, [])


def audit(products, cat_cfg=None, gen=None):
    """(errors, warnings) for sync_catalog.py report item 11."""
    cat_cfg = cat_cfg or categories.load()
    gen = gen or load()
    errors, warnings = [], []
    ids = {p["id"] for p in products}
    real = {p["campaign"] for p in products}

    listed = {}
    for t in gen["themes"]:
        for c in t["campaigns"]:
            listed.setdefault(c, []).append(t["slug"])
    for c in gen["unthemed"]:
        listed.setdefault(c, []).append("unthemed")
    for c in sorted(real - set(listed)):
        errors.append(f"campaign {c} is in products.json but not in generator.json themes or unthemed")
    for c in sorted(set(listed) - real):
        errors.append(f"generator.json lists campaign {c}, which has no products in products.json")
    for c, where in sorted(listed.items()):
        if len(where) > 1:
            errors.append(f"campaign {c} is listed more than once in generator.json ({', '.join(where)})")

    tabs = {t["slug"]: {s["slug"] for s in t["subs"]} for t in cat_cfg["tabs"]}

    def check_pattern(pat, where):
        tab, _, sub = pat.partition("/")
        if tab not in tabs or (sub and sub not in tabs[tab]):
            errors.append(f"generator.json {where}: '{pat}' is not a categories.json tab or tab/sub")

    for slot, spec in gen["slots"].items():
        for pat in spec["allow"] + spec.get("fan_gear", []):
            check_pattern(pat, f"slots.{slot}")
    for s in gen["base_slots"] + gen["extra_slots"]:
        if s not in gen["slots"]:
            errors.append(f"generator.json names slot '{s}', which isn't in slots")
    for n, rule in enumerate(gen["rules"], 1):
        for key in ("never", "if", "not_with", "only_with"):
            for pat in rule.get(key, []):
                check_pattern(pat, f"rule {n} {key}")
    theme_slugs = {t["slug"] for t in gen["themes"]}
    for t in gen["themes"]:
        b = t.get("borrow")
        if b:
            if b["from"] not in theme_slugs:
                errors.append(f"generator.json theme {t['slug']} borrows from unknown theme '{b['from']}'")
            for s in b["slots"]:
                if s not in gen["slots"]:
                    errors.append(f"generator.json theme {t['slug']} borrows unknown slot '{s}'")
    for pid in gen["exclude"]:
        if pid not in ids:
            errors.append(f"generator.json exclude lists {pid}, which isn't in products.json")

    codes = {}
    for p in products:
        codes.setdefault(short_code(p["id"]), []).append(p["id"])
    for code, same in codes.items():
        if len(same) > 1:
            errors.append(f"outfit-link code {code} is shared by {', '.join(same)}; change short_code() "
                          "here and shortCode() in generator/index.html")

    if errors:
        return errors, warnings
    recs = records(products, cat_cfg, gen)
    for slug in ["any"] + [t["slug"] for t in gen["themes"]]:
        pools = build_pools(recs, gen, slug)
        for slot, pool in pools.items():
            if len(pool) < MIN_POOL:
                warnings.append(f"theme {slug}, slot {slot}: only {len(pool)} product(s) to shuffle")
        if not feasible(pools, gen, float("inf")):
            errors.append(f"theme {slug} can't build any outfit at all")
    return errors, warnings


def main():
    with open(PRODUCTS_JSON, encoding="utf-8") as f:
        products = json.load(f)
    cat_cfg, gen = categories.load(), load()
    recs = records(products, cat_cfg, gen)
    slots = list(gen["slots"])
    print(f"{'theme':16}" + "".join(f"{s:>11}" for s in slots) + "   budgets that can build an outfit")
    for slug in ["any"] + [t["slug"] for t in gen["themes"]]:
        pools = build_pools(recs, gen, slug)
        sizes = "".join(f"{len(pools[s]):>5} ({sum(priced(r['p']) for r in pools[s]):>3})" for s in slots)
        ok = [f"<${b}" for b in gen["budgets"] if feasible(pools, gen, b)]
        print(f"{slug:16}{sizes}   {', '.join(ok) or 'none'}")
    print("\n(each slot: products, then priced products in brackets)")
    errors, warnings = audit(products, cat_cfg, gen)
    for e in errors:
        print("ERROR:", e)
    for w in warnings:
        print("WARN:", w)
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
