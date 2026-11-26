#!/usr/bin/env python3
"""
Thin-section routing for Pinterest pins: picks the board/section a pin goes
to from the rules in pinterest/pin_settings.json "routing", so the
account's thin sections fill up.

make_pinterest_csv.py calls route() on every batch. For a batch starting on
or after routing.applies_from it moves the pins; for an earlier batch
(already uploaded) it only lists what it would have moved. Either way the
report prints the thin-section counts (before, this batch, after).

Run directly to scan every past pinterest_bulk_*.csv and write the backfill
list (pins already on Pinterest that belong in a thin section) to
pinterest/thin_section_backfill.md:
    py -3 pin_routing.py
    py -3 pin_routing.py --counts     (just print the current thin counts)

Rules (all prices: products.json "price", the price SHEIN charges before
any coupon; an outfit's total is the sum of every item its page's cards
link to, and it has no total when any item has no price, i.e. Amazon or
Awin, or when currencies mix; no price, no price rule):

  price_tiers        a pin on one of these boards goes to its "under"
                     section when the price/total is strictly below "at"
                     (Under $50 = under CA$50.00), else its "over" section
                     (Splurge Worthy ($50+) = CA$50.00 and up). A pin hand-set
                     to the wrong tier is always corrected.
  streetwear_splurge Streetwear / Motor Streetwear outfits at or over "at",
                     and streetwear jackets and sneakers (a product from a
                     streetwear campaign or pinned to a streetwear board)
                     at or over "at", qualify for that section.
  basics             a product on Men's Basics & Essentials under "at"
                     qualifies for Under $20; any product whose name says
                     shorts plus a sweat/fleece/lounge/gym word qualifies
                     for Shorts.
  running            any product whose name has a running keyword qualifies
                     for Men's Gym & Training Outfits / Running. The batch
                     report warns when a batch has fewer than
                     min_per_batch of them (the weekly sourcing slots).
  stadium            every "every"-th Game Day outfit (1st, 4th, 7th...,
                     file order) whose section isn't in stay_sections moves
                     to Men's Stadium Streetwear, and so does any pin with
                     "outfit_check": true (the weekly Stadium Streetwear
                     Outfit Check). Section: Off Duty when the outfit has an
                     officially licensed item (categories.json fan_gear),
                     else Team Colours; Under $50 also qualifies when the
                     total is under CA$50.

Thin-section priority: when a pin qualifies for more than one section, the
thin section with the fewest pins wins, while it's under thin.target;
otherwise the pin keeps its hand-set section (or, for a stadium move,
Team Colours / Off Duty). Counts start from thin.counts, which covers the
batches in thin.counted_batches; any other batch's pinterest_bulk CSV is
added on top, so a new batch is counted once its CSV is written. Pins
moved by hand on Pinterest (the backfill) aren't in any CSV: update
thin.counts after moving them.

A pin with "section_locked": true keeps its board and section.
"""

import argparse
import csv
import glob
import json
import os
import posixpath
import re
import sys
import urllib.parse
from datetime import date, datetime, timezone

import categories

REPO = os.path.dirname(os.path.abspath(__file__))
PIN_DIR = os.path.join(REPO, "pinterest")
SETTINGS_JSON = os.path.join(PIN_DIR, "pin_settings.json")
PRODUCTS_JSON = os.path.join(REPO, "products.json")
BACKFILL_MD = os.path.join(PIN_DIR, "thin_section_backfill.md")
SITE = "https://thatfootball12.github.io/thatfootball12-links/"
# Old CSVs used this misspelling; the account's board is "Men's Basics & Essentials".
BOARD_ALIASES = {"Men's Basic & Essentials": "Men's Basics & Essentials"}
CSV_RE = re.compile(r"pinterest_bulk_(.+?)(?:_\d+)?\.csv$")
CARD_HREF_RE = re.compile(r'<a class="card" href="([^"]+)"')


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# --- prices ----------------------------------------------------------------

def total_cents(items):
    """Summed price in cents, or None when any item has no price, the
    currencies mix, or there are no items."""
    if not items or any(i.get("price") is None for i in items):
        return None
    if len({i.get("currency") for i in items}) > 1:
        return None
    return sum(round(i["price"] * 100) for i in items)


def money(cents, items):
    if cents is None:
        missing = sorted({i.get("retailer") or "?" for i in items if i.get("price") is None})
        return "no total (" + "/".join(missing) + " item)" if missing else "no price"
    symbol = "CA$" if all(i.get("currency") == "CAD" for i in items) else "$"
    return f"{symbol}{cents / 100:.2f}"


def outfit_items(rel, products):
    """products.json records the outfit page's cards link to (same rule as
    make_pinterest_csv.resolve and make_outfit_pin.campaign_products)."""
    page = os.path.join(REPO, rel, "index.html")
    if not os.path.isfile(page):
        return []
    with open(page, encoding="utf-8") as f:
        hrefs = CARD_HREF_RE.findall(f.read())
    pages = {posixpath.normpath(posixpath.join(rel, h)) + "/index.html" for h in hrefs}
    return [p for p in products if p["detail_page_url"] in pages]


# --- counts ----------------------------------------------------------------

def thin_keys(routing):
    return [(t["board"], t["section"]) for t in routing["thin"]["sections"]]


def split_board(value):
    """'Board/Section' -> (board, section). Board names never contain '/',
    section names can (Date Night/Night Out), so split at the first one."""
    board, _, section = value.partition("/")
    return BOARD_ALIASES.get(board, board), section


def csv_batches():
    """{batch: [rows]} from every pinterest_bulk_*.csv (split files merged)."""
    out = {}
    for path in sorted(glob.glob(os.path.join(PIN_DIR, "pinterest_bulk_*.csv"))):
        m = CSV_RE.search(os.path.basename(path))
        if not m:
            continue
        with open(path, encoding="utf-8", newline="") as f:
            out.setdefault(m.group(1), []).extend(csv.DictReader(f))
    return out


def current_counts(routing, exclude_batch=None):
    """Thin-section counts: thin.counts plus any CSV batch not already in
    thin.counted_batches (and not the batch being built)."""
    thin = routing["thin"]
    counts = {(t["board"], t["section"]): int(t.get("count", 0)) for t in thin["sections"]}
    counted = set(thin.get("counted_batches", []))
    for batch, rows in csv_batches().items():
        if batch in counted or batch == exclude_batch:
            continue
        for r in rows:
            key = split_board(r["Pinterest board"])
            if key in counts:
                counts[key] += 1
    return counts


# --- rules -----------------------------------------------------------------

def _has(name, words):
    return categories._has(name or "", words)


def theme_of(pin):
    """First segment of the outfit id / the product record's theme."""
    if pin["type"] == "outfit":
        return pin["id"].strip("/").split("/")[0]
    rec = pin.get("rec") or {}
    return rec.get("theme")


def is_running(rec, rule):
    return bool(rec) and _has(rec.get("name"), rule["keywords"])


def is_basic_shorts(rec, rule):
    name = (rec or {}).get("name")
    return _has(name, ["shorts", "short"]) and _has(name, rule["keywords"])


def stadium_section(pin, rule, cat_cfg):
    fan = any(categories.is_fan_gear(i, cat_cfg) for i in pin.get("items") or [])
    return rule["team_gear_section"] if fan else rule["team_colours_section"]


def streetwear_product(pin, rule):
    rec = pin.get("rec") or {}
    if pin["board"] not in rule["product_boards"] and theme_of(pin) not in rule["themes"]:
        return False
    for m in rule["products"]:
        if rec.get("item_type") == m["item_type"] and (
                not m.get("keywords") or _has(rec.get("name"), m["keywords"])):
            return True
    return False


def candidates(pin, routing, cat_cfg, stadium_move):
    """(base (board, section), [(board, section, reason)], [fix notes]).
    base is where the pin goes when no thin section wins."""
    cents = total_cents(pin.get("items") or [])
    base = (pin["board"], (pin.get("section") or "").strip())
    cands, fixes = [], []
    rec = pin.get("rec") if pin["type"] == "product" else None

    st = routing["stadium"]
    if stadium_move:
        why = "Stadium Streetwear Outfit Check" if pin.get("outfit_check") else \
              f"1 in {st['every']} Game Day outfits"
        base = (st["board"], stadium_section(pin, st, cat_cfg))
        cands.append((*base, why))
        if cents is not None and cents < st["under_at"] * 100:
            cands.append((st["board"], st["under_section"], f"{why}, total under ${st['under_at']}"))
        return base, cands, fixes

    for t in routing["price_tiers"]:
        if pin["board"] != t["board"] or pin["type"] not in t["types"]:
            continue
        tier_sections = {t["under"], t.get("over")} - {None}
        if cents is None:
            if base[1] in tier_sections:
                fixes.append(f"in {base[1]} but has no total")
            continue
        right = t["under"] if cents < t["at"] * 100 else t.get("over")
        if base[1] in tier_sections and base[1] != right:
            fixes.append(f"was in {base[1]}, price doesn't fit")
            if right:
                base = (t["board"], right)
            elif t["board"] == st["board"]:
                base = (st["board"], stadium_section(pin, st, cat_cfg))
        if right:
            cands.append((t["board"], right, "price tier"))

    sw = routing["streetwear_splurge"]
    if cents is not None and cents >= sw["at"] * 100:
        if pin["type"] == "outfit" and theme_of(pin) in sw["themes"]:
            cands.append((sw["board"], sw["section"], "streetwear outfit $50+"))
        elif pin["type"] == "product" and streetwear_product(pin, sw):
            cands.append((sw["board"], sw["section"], "streetwear jacket/sneakers $50+"))

    if rec:
        b = routing["basics"]
        if pin["board"] == b["board"] and cents is not None and cents < b["under_at"] * 100:
            cands.append((b["board"], b["under_section"], f"basic under ${b['under_at']}"))
        if is_basic_shorts(rec, b["shorts"]):
            cands.append((b["board"], b["shorts"]["section"], "sweat/fleece/lounge/gym shorts"))
        r = routing["running"]
        if is_running(rec, r):
            cands.append((r["board"], r["section"], "running"))
    return base, cands, fixes


def stadium_moves(pins, routing):
    """ids of the pins that move to Men's Stadium Streetwear: every
    'every'-th eligible Game Day outfit (1st, 4th, ...) plus outfit checks."""
    st = routing["stadium"]
    eligible = [p for p in pins if p["type"] == "outfit" and not p.get("outfit_check")
                and not p.get("section_locked") and p["board"] == st["from_board"]
                and (p.get("section") or "").strip() not in st["stay_sections"]]
    moves = {id(p) for i, p in enumerate(eligible) if i % st["every"] == 0}
    moves |= {id(p) for p in pins if p.get("outfit_check") and not p.get("section_locked")}
    return moves


def route(pins, settings, counts, apply, cat_cfg=None, cap=True):
    """Decides every pin's section. counts ({(board, section): n}) is
    updated in place with the pins that land in a thin section. With apply,
    the pins' board/section are changed. Returns a list of decisions
    (dicts) for the pins whose section changes."""
    routing = settings["routing"]
    cat_cfg = cat_cfg or categories.load()
    target = routing["thin"]["target"]
    thin = set(thin_keys(routing))
    moves = stadium_moves(pins, routing)
    decisions = []
    for p in pins:
        current = (p["board"], (p.get("section") or "").strip())
        if p.get("section_locked") or p["type"] == "gift":
            if current in counts:
                counts[current] += 1
            continue
        base, cands, fixes = candidates(p, routing, cat_cfg, id(p) in moves)
        # A stadium move's base is its own candidate (with its reason).
        base_why = next((c[2] for c in cands if c[:2] == base), "hand-set")
        options = [(*base, base_why)] + [c for c in cands if c[:2] != base]
        open_thin = [c for c in options if c[:2] in thin and (not cap or counts[c[:2]] < target)]
        # Fewest pins first; on a tie the earlier option (hand-set first).
        choice = min(open_thin, key=lambda c: counts[c[:2]]) if open_thin else options[0]
        key = choice[:2]
        # Count where the pin really ends up: unapplied suggestions don't move it.
        landed = key if apply else current
        if landed in counts:
            counts[landed] += 1
        if key != current:
            decisions.append({"pin": p, "from": current, "to": key,
                              "reason": "; ".join([choice[2]] + fixes) if choice[2] != "hand-set"
                              else "; ".join(fixes) or "hand-set",
                              "price": money(total_cents(p.get("items") or []), p.get("items") or [])})
            if apply:
                p["board"], p["section"] = key
        elif fixes:
            decisions.append({"pin": p, "from": current, "to": key, "reason": "; ".join(fixes),
                              "price": money(total_cents(p.get("items") or []), p.get("items") or []),
                              "warning": True})
    return decisions


def running_count(pins, settings):
    r = settings["routing"]["running"]
    return sum(1 for p in pins if p["type"] == "product" and is_running(p.get("rec"), r))


def fmt(key):
    board, section = key
    return f"{board} › {section}" if section else board


def report_lines(batch_pins, settings, before, after, decisions, applied):
    """Markdown for make_pinterest_csv's report."""
    routing = settings["routing"]
    target = routing["thin"]["target"]
    L = ["## Thin sections", "",
         f"Pins per thin section (target {target}). Before = live and scheduled "
         "pins counted so far (thin.counts + other batches' CSVs).", "",
         "| Board | Section | Before | This batch | After |", "|---|---|---|---|---|"]
    for key in thin_keys(routing):
        n = after[key] - before[key]
        flag = "" if after[key] >= target else " (thin)"
        L.append(f"| {key[0]} | {key[1]} | {before[key]} | {n} | {after[key]}{flag} |")
    L.append("")
    moved = [d for d in decisions if not d.get("warning")]
    if moved:
        L += ["### Routed by pin_settings.json routing" if applied else
              "### Routing suggestions (NOT applied: batch is before routing.applies_from)", ""]
        L += [f"- {d['pin']['title'].strip()} ({d['price']}): {fmt(d['from'])} → "
              f"**{fmt(d['to'])}** — {d['reason']}" for d in moved] + [""]
    r = routing["running"]
    n = running_count(batch_pins, settings)
    if n < r["min_per_batch"]:
        L += [f"**Running slots:** {n} running product pin(s) this batch; weekly sourcing "
              f"should include {r['min_per_batch']}–{r['max_per_batch']}.", ""]
    return L


def warnings_from(decisions):
    return [f"{d['pin']['type']} {d['pin']['id']}: {d['reason']} ({fmt(d['from'])})"
            for d in decisions if d.get("warning")]


# --- backfill --------------------------------------------------------------

def pin_from_row(row, products, by_page):
    """A pin dict (type, id, board, section, title, items, rec) for a CSV
    row, or None for a gift pin or a link that's no longer a page."""
    url = urllib.parse.urlsplit(row["Link"])
    full = urllib.parse.urlunsplit(url._replace(query="", fragment=""))
    if not full.startswith(SITE):
        return None
    rel = full[len(SITE):].strip("/")
    board, section = split_board(row["Pinterest board"])
    pin = {"title": row["Title"], "board": board, "section": section,
           "publish": row["Publish date"]}
    rec = by_page.get(rel + "/index.html")
    if rec and not rel.startswith("gift-guide"):
        return {**pin, "type": "product", "id": rec["id"], "rec": rec, "items": [rec]}
    if rel.startswith("outfits/") and rel.count("/") == 2:
        return {**pin, "type": "outfit", "id": rel[len("outfits/"):],
                "items": outfit_items(rel, products)}
    return None


def backfill(settings, products):
    """Every CSV pin whose section routing would change to a thin section
    (uncapped), batch by batch in date order."""
    routing = settings["routing"]
    thin = set(thin_keys(routing))
    by_page = {p["detail_page_url"]: p for p in products}
    cat_cfg = categories.load()
    batches = csv_batches()
    order = sorted(batches, key=lambda b: min(r["Publish date"] for r in batches[b]))
    out = []
    for batch in order:
        pins = [p for p in (pin_from_row(r, products, by_page) for r in batches[batch]) if p]
        scratch = {k: 0 for k in thin}
        for d in route(pins, settings, scratch, apply=False, cat_cfg=cat_cfg, cap=False):
            # Already in a thin section: leave it there (no thin-to-thin shuffles).
            if (d["to"] in thin and d["from"] not in thin) or d.get("warning"):
                out.append({**d, "batch": batch})
    return out


def write_backfill(settings, products):
    rows = backfill(settings, products)
    target = settings["routing"]["thin"]["target"]
    counts = current_counts(settings["routing"])
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    L = ["# Thin-section backfill", "",
         f"Generated by `py -3 pin_routing.py` on {date.today():%Y-%m-%d} from every "
         "pinterest/pinterest_bulk_*.csv. Pins already on Pinterest (or scheduled) "
         "that the routing rules in pin_settings.json would put in a thin section. "
         "Move them by hand on Pinterest (pin › Edit › Board/Section), then add the "
         "moves to routing.thin.counts.", "",
         f"Target {target} pins per section. \"After\" is the section's count if every "
         "listed pin above it (in that section's table) is moved; a pin past the target "
         "is marked optional.", ""]
    by_to = {}
    for d in rows:
        if not d.get("warning"):
            by_to.setdefault(d["to"], []).append(d)
    for key in thin_keys(settings["routing"]):
        ds = by_to.get(key, [])
        n = counts[key]
        L += [f"## {fmt(key)}", "", f"Now {n}; {len(ds)} pin(s) qualify.", ""]
        if not ds:
            L += ["Nothing in the past CSVs qualifies.", ""]
            continue
        L += ["| # | Title | Batch | Status | Current board › section | Price / outfit total | Why | After |",
              "|---|---|---|---|---|---|---|---|"]
        for i, d in enumerate(ds, 1):
            # A pin can qualify for more than one thin section: it's listed
            # in each, so "After" assumes it goes here.
            n += 1
            status = "live" if d["pin"]["publish"] <= now else "scheduled"
            note = "" if n <= target else " (optional)"
            title = d["pin"]["title"].strip().replace("|", "\\|")
            L.append(f"| {i} | {title} | {d['batch']} | {status} | {fmt(d['from'])} | "
                     f"{d['price']} | {d['reason']} | {n}{note} |")
        L.append("")
    warn = [d for d in rows if d.get("warning")]
    if warn:
        L += ["## Price-tier problems in live pins", "",
              "In a price-tier section whose price doesn't fit, with no right tier to move "
              "to on that board:", ""]
        L += [f"- {d['pin']['title'].strip()} ({d['batch']}, {d['price']}): "
              f"{fmt(d['from'])} — {d['reason']}" for d in warn] + [""]
    with open(BACKFILL_MD, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(L))
    return rows, L


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--counts", action="store_true", help="print the current thin counts only")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    settings = load_json(SETTINGS_JSON)
    if args.counts:
        target = settings["routing"]["thin"]["target"]
        for key, n in current_counts(settings["routing"]).items():
            print(f"{n:>3}/{target}  {fmt(key)}")
        return
    rows, lines = write_backfill(settings, load_json(PRODUCTS_JSON))
    print("\n".join(lines))
    print(f"\nWrote {os.path.relpath(BACKFILL_MD, REPO)}")


if __name__ == "__main__":
    main()
