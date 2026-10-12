#!/usr/bin/env python3
"""
Places products.json records into the products/ page's tabs and sub-chips,
using the rules in categories.json. products/index.html applies the same
rules in the browser (placeProduct() there); this module is the Python
copy that sync_catalog.py uses to check the catalog (report item 10) and
that prints the per-tab counts.

Run directly to print every tab and sub-chip with its count:
    py -3 categories.py
    py -3 categories.py --list      (also list each product)

Also home to added_from_campaign(), which turns a campaign slug's date
("gameday-oct-19-2") into the YYYY-MM-DD "added" date that the products/
page's Newest sort uses. sync_catalog.py --append calls it for new records.
"""

import datetime
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
CATEGORIES_JSON = os.path.join(REPO, "categories.json")

MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "june": 6,
          "jul": 7, "july": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12}
CAMPAIGN_DATE_RE = re.compile(r"(?:^|-)(" + "|".join(MONTHS) + r")-(\d{1,2})(?:-\d+)?$")
ADDED_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def load():
    with open(CATEGORIES_JSON, encoding="utf-8") as f:
        return json.load(f)


def _has(name, words):
    """True if any of words appears in name as a whole word, case-insensitive.
    Same test as hasWord() in products/index.html: the characters on either
    side of the match must not be a letter or digit."""
    low = name.lower()
    for w in words:
        start = 0
        while True:
            i = low.find(w, start)
            if i == -1:
                break
            before = low[i - 1] if i > 0 else ""
            after = low[i + len(w)] if i + len(w) < len(low) else ""
            if not (before.isascii() and before.isalnum()) and not (after.isascii() and after.isalnum()):
                return True
            start = i + 1
    return False


def is_fan_gear(p, cfg):
    fg = cfg["fan_gear"]
    if p["id"] in fg["exclude"]:
        return False
    if p["id"] in fg["include"]:
        return True
    name = p.get("name") or ""
    if _has(name, fg["licensed_keywords"]):
        return True
    return _has(name, fg["licensed_brands"]) and _has(name, fg["teams"])


def team_only(p, cfg):
    """A team name in the name with nothing that shows it's licensed: not
    Fan Gear, but worth a human look (sync_catalog.py warns)."""
    fg = cfg["fan_gear"]
    if p["id"] in fg["exclude"] or p["id"] in fg["include"]:
        return False
    return _has(p.get("name") or "", fg["teams"]) and not is_fan_gear(p, cfg)


def _tab(cfg, slug):
    return next((t for t in cfg["tabs"] if t["slug"] == slug), None)


def _match_sub(tab, name):
    subs = {s["slug"]: s for s in tab["subs"]}
    for slug in tab.get("match_order") or [s["slug"] for s in tab["subs"]]:
        if subs[slug]["keywords"] and _has(name, subs[slug]["keywords"]):
            return slug
    return None


def place(p, cfg):
    """(tab_slug, sub_slug_or_None) for a product, or None if it's hidden
    or its item_type isn't mapped (the latter is a sync_catalog.py error)."""
    if p["id"] in cfg["hidden"]:
        return None
    ov = cfg["overrides"].get(p["id"])
    if ov:
        tab, _, sub = ov.partition("/")
        return tab, sub or None
    name = p.get("name") or ""
    if is_fan_gear(p, cfg):
        tab = cfg["fan_gear"]["tab"]
        return tab, _match_sub(_tab(cfg, tab), name)
    m = cfg["item_types"].get(p.get("item_type"))
    if not m:
        return None
    return m["tab"], _match_sub(_tab(cfg, m["tab"]), name) or m.get("sub")


def audit(products, cfg):
    """(errors, warnings): lists of strings. Errors fail sync_catalog.py."""
    errors, warnings = [], []
    ids = {p["id"] for p in products}
    tabs = {t["slug"]: {s["slug"] for s in t["subs"]} for t in cfg["tabs"]}

    for t in cfg["tabs"]:
        for slug in t.get("match_order") or []:
            if slug not in tabs[t["slug"]]:
                errors.append(f"categories.json: tab {t['slug']} match_order names unknown sub '{slug}'")
    for it, m in cfg["item_types"].items():
        if m["tab"] not in tabs:
            errors.append(f"categories.json: item_type '{it}' maps to unknown tab '{m['tab']}'")
        elif m.get("sub") and m["sub"] not in tabs[m["tab"]]:
            errors.append(f"categories.json: item_type '{it}' maps to unknown sub '{m['tab']}/{m['sub']}'")
    if cfg["fan_gear"]["tab"] not in tabs:
        errors.append(f"categories.json: fan_gear.tab '{cfg['fan_gear']['tab']}' is not a tab")
    for pid, dest in cfg["overrides"].items():
        tab, _, sub = dest.partition("/")
        if tab not in tabs or (sub and sub not in tabs[tab]):
            errors.append(f"categories.json: override for {pid} names unknown '{dest}'")
    for where, lst in (("overrides", cfg["overrides"]), ("hidden", cfg["hidden"]),
                       ("fan_gear.include", cfg["fan_gear"]["include"]),
                       ("fan_gear.exclude", cfg["fan_gear"]["exclude"])):
        for pid in lst:
            if pid not in ids:
                errors.append(f"categories.json: {where} lists {pid}, which isn't in products.json")

    for p in products:
        if p.get("item_type") not in cfg["item_types"]:
            errors.append(f"{p['id']}: item_type {p.get('item_type')!r} is not in categories.json item_types")
        added = p.get("added")
        if not (isinstance(added, str) and ADDED_RE.match(added)):
            errors.append(f"{p['id']}: added {added!r} is not a YYYY-MM-DD date")
        else:
            try:
                datetime.date.fromisoformat(added)
            except ValueError:
                errors.append(f"{p['id']}: added {added!r} is not a real date")
        if p["id"] in cfg["hidden"]:
            continue
        if team_only(p, cfg):
            warnings.append(f"{p['id']}: names a team but nothing shows it's licensed, so it's not in "
                            f"Fan Gear (add to fan_gear.include or .exclude to decide): {p.get('name')}")
        placed = place(p, cfg)
        # An override with no sub ("accessories") is a deliberate choice.
        if placed and placed[1] is None and tabs.get(placed[0]) and p["id"] not in cfg["overrides"]:
            warnings.append(f"{p['id']}: matches no {placed[0]} sub-chip (shows under All only): {p.get('name')}")
    return errors, warnings


def added_from_campaign(campaign, today=None):
    """YYYY-MM-DD from the campaign slug's month-day, in whichever year puts
    it nearest today (a "jan-4" batch built in late December is next year's).
    None if the slug has no date."""
    m = CAMPAIGN_DATE_RE.search(campaign or "")
    if not m:
        return None
    today = today or datetime.date.today()
    month, day = MONTHS[m.group(1)], int(m.group(2))
    best = None
    for year in (today.year - 1, today.year, today.year + 1):
        try:
            d = datetime.date(year, month, day)
        except ValueError:
            continue
        if best is None or abs((d - today).days) < abs((best - today).days):
            best = d
    return best.isoformat() if best else None


def main():
    with open(os.path.join(REPO, "products.json"), encoding="utf-8") as f:
        products = json.load(f)
    cfg = load()
    listing = "--list" in sys.argv
    placed = [(p, place(p, cfg)) for p in products]
    print(f"{len(products)} products, {sum(1 for _, x in placed if x)} shown, "
          f"{sum(1 for p in products if p['id'] in cfg['hidden'])} hidden")
    for t in cfg["tabs"]:
        in_tab = [(p, x) for p, x in placed if x and x[0] == t["slug"]]
        print(f"\n{t['label']} ({len(in_tab)})")
        for s in t["subs"] + [{"slug": None, "label": "(no sub-chip)"}]:
            rows = [p for p, x in in_tab if x[1] == s["slug"]]
            if rows or s["slug"]:
                print(f"  {s['label']}: {len(rows)}")
            if listing:
                for p in rows:
                    print(f"      {p['retailer']:6} {p['name'][:90]}")
    errors, warnings = audit(products, cfg)
    for e in errors:
        print("ERROR:", e)
    for w in warnings:
        print("WARN:", w)


if __name__ == "__main__":
    main()
