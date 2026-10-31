#!/usr/bin/env python3
"""
Builds the weekly Pinterest bulk-upload CSV from a batch's pin copy.

Usage:
    py -3 make_pinterest_csv.py oct-19             (reads pinterest/pins_oct-19.json)
    py -3 make_pinterest_csv.py oct-19 --dry-run   (validate + report, write nothing)

Inputs (all in pinterest/):
    pins_<batch>.json   one entry per pin, copy supplied by hand:
        {"batch": "oct-19", "week_start": "2026-10-19", "pins": [
          {"type": "outfit", "id": "gameday/gameday-oct-19", ...},
          {"type": "product", "id": "trending-products/trending-products-oct-19-3/polo", ...}]}
      Every pin has title, description, hashtags (list, each starting
      with #), alt_text, board and section ("" for none); keywords (list)
      is optional. An outfit id is its folder under outfits/; a product
      id is its products.json id. week_start is the batch week's Monday.
    pin_settings.json   the disclosure appended to every description
      (disclosure_shein_only when every item in the pin is SHEIN, else
      disclosure; a pin with a retailer outside disclosure_retailers,
      e.g. Awin, is an error), the AI line added for AI-image pins (every outfit pin, and product
      pins whose retailer is in ai_image_retailers), and the account's
      boards with their sections. Pinterest CREATES any board or section
      named in the CSV that doesn't exist, so these must match the
      account exactly; anything not listed is an error.

Per pin:
    Link        the outfit or product page on the live site.
    Media URL   outfit-pin.jpg / product-pin.jpg (falls back to
                outfit-preview.jpg with a warning, or the product photo
                for products make_product_pin.py --pick didn't choose).
                A batch where no SHEIN product pin has a product-pin.jpg
                is an error: make_product_pin.py wasn't run.
    Description copy + disclosure [+ AI line] + hashtags.
    Board       "Board/Section". A section whose own name contains "/"
                can't be expressed that way, so those pins get the board
                only and the report lists them to move by hand.

Schedule: across week_start's Mon-Sun, outfit pins 2 a day (gameday
first, then file order), product pins each onto the day with the fewest
pins so far, every day's pins spread evenly between 08:00 and 21:00
Atlantic time, written in UTC (Pinterest reads Publish date as UTC).

Validation runs before anything is written; on any problem the script
lists them all and writes no CSV: Link and Media URL must return 200 on
the live site (so push the pin images first), title <= 100 and full
description <= 500 characters (Pinterest's limits), boards/sections in
pin_settings.json, no duplicate pins/images/titles, no publish time in
the past, no "$" in the copy of a pin with an Amazon item (Amazon
prices can't be shown), no product pin of a SHEIN product whose seller
is "marketplace" (a third-party store; see sellers.py). Product pins
whose seller is still "unchecked" go through, listed in the report.

Output: pinterest/pinterest_bulk_<batch>.csv in Pinterest's own
template layout (pinterest_bulk_<batch>_1.csv, _2.csv, ... over 200
rows, Pinterest's per-file limit) and pinterest_bulk_<batch>_report.md:
pins per day, plus the manual follow-ups the CSV can't carry (alt text
and the AI-modified label have no column).
"""

import argparse
import csv
import json
import os
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import gift_guide
import sellers

REPO = os.path.dirname(os.path.abspath(__file__))
PIN_DIR = os.path.join(REPO, "pinterest")
SETTINGS_JSON = os.path.join(PIN_DIR, "pin_settings.json")
PRODUCTS_JSON = os.path.join(REPO, "products.json")
SITE = "https://thatfootball12.github.io/thatfootball12-links/"

# Pinterest's sample template (help.pinterest.com, "Bulk upload Pins").
COLUMNS = ["Title", "Media URL", "Pinterest board", "Thumbnail",
           "Description", "Link", "Publish date", "Keywords"]
MAX_ROWS = 200
MAX_TITLE = 100
MAX_DESC = 500
OUTFITS_PER_DAY = 2
DAY_START_H, DAY_END_H = 8, 21      # Atlantic time
SLOT_MIN = 15                        # publish times rounded to this
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; TF12-PinCSV/1.0)"}


# --- Atlantic time (no tzdata on Windows; Canadian DST rule) -------------

def nth_sunday(year, month, n):
    d = date(year, month, 1)
    d += timedelta(days=(6 - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def atlantic_to_utc(local):
    """local: naive Atlantic wall time. ADT (UTC-3) from the 2nd Sunday of
    March 02:00 to the 1st Sunday of November 02:00, else AST (UTC-4)."""
    y = local.year
    dst_on = datetime.combine(nth_sunday(y, 3, 2), datetime.min.time()) + timedelta(hours=2)
    dst_off = datetime.combine(nth_sunday(y, 11, 1), datetime.min.time()) + timedelta(hours=2)
    offset = 3 if dst_on <= local < dst_off else 4
    return (local + timedelta(hours=offset)).replace(tzinfo=timezone.utc)


# --- inputs ----------------------------------------------------------------

def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def page_url(rel_dir):
    return SITE + rel_dir.strip("/").replace("\\", "/") + "/"


def resolve(pin, products, by_id, settings, problems, warnings):
    """Adds link, media, ai, has_amazon to pin. Returns False if it can't."""
    label = f"{pin.get('type')} {pin.get('id')}"
    if pin.get("type") == "outfit":
        rel = "outfits/" + pin["id"].strip("/")
        if not os.path.isfile(os.path.join(REPO, rel, "index.html")):
            problems.append(f"{label}: no page at {rel}/index.html")
            return False
        for name in ("outfit-pin.jpg", "outfit-preview.jpg"):
            if os.path.isfile(os.path.join(REPO, rel, name)):
                break
        else:
            problems.append(f"{label}: no outfit-pin.jpg or outfit-preview.jpg")
            return False
        if name != "outfit-pin.jpg":
            warnings.append(f"{label}: no outfit-pin.jpg, using {name} (run make_outfit_pin.py)")
        pin["link"] = page_url(rel)
        pin["media"] = page_url(rel) + name
        pin["ai"] = True
        items = [p for p in products if p["detail_page_url"].startswith(rel + "/")]
        if not items:
            problems.append(f"{label}: no products.json records under {rel}/")
            return False
        pin["retailers"] = {p.get("retailer") for p in items}
        pin["has_amazon"] = "Amazon" in pin["retailers"]
        return True

    if pin.get("type") == "product":
        rec = by_id.get(pin["id"])
        if rec is None:
            problems.append(f"{label}: not in products.json")
            return False
        if rec.get("image_pending"):
            problems.append(f"{label}: image_pending, no photo yet")
            return False
        if sellers.refused(rec):
            problems.append(f"{label}: {sellers.REFUSED}")
            return False
        pin["seller_unchecked"] = sellers.unchecked(rec)
        rel = os.path.dirname(rec["detail_page_url"])
        if gift_guide.listing_only(rec):
            # No detail page: the pin links to the gift guide and uses
            # its holiday pin image.
            img = gift_guide.pin_image(rec)
            if not img or not os.path.isfile(os.path.join(REPO, img)):
                problems.append(f"{label}: gift guide listing with no holiday pin image ({img})")
                return False
            pin["media"] = SITE + img
        elif os.path.isfile(os.path.join(REPO, rel, "product-pin.jpg")):
            pin["media"] = page_url(rel) + "product-pin.jpg"
            pin["price_pin"] = True
        else:
            # Only make_product_pin.py --pick's choices get a price pin;
            # main() fails the batch if none of its pins has one.
            pin["media"] = SITE + rec["image"]
        pin["shein_page"] = rec.get("retailer") == "SHEIN" and not gift_guide.listing_only(rec)
        pin["link"] = page_url(rel)
        pin["ai"] = rec.get("retailer") in settings.get("ai_image_retailers", [])
        pin["retailers"] = {rec.get("retailer")}
        pin["has_amazon"] = rec.get("retailer") == "Amazon"
        return True

    problems.append(f"{label}: type must be 'outfit' or 'product'")
    return False


def disclosure(pin, settings):
    """The SHEIN-only wording for a pin whose items are all SHEIN, else
    the full one (SHEIN + Amazon)."""
    if pin["retailers"] == {"SHEIN"}:
        return settings["disclosure_shein_only"].strip()
    return settings["disclosure"].strip()


def full_description(pin, settings):
    parts = [pin["description"].strip(), disclosure(pin, settings)]
    if pin["ai"]:
        parts.append(settings["ai_line"].strip())
    if pin["hashtags"]:
        parts.append(" ".join(pin["hashtags"]))
    return " ".join(parts)


def board_field(pin):
    """Returns (csv value, section that couldn't be set or None)."""
    section = (pin.get("section") or "").strip()
    if not section:
        return pin["board"], None
    if "/" in section:
        return pin["board"], section
    return f"{pin['board']}/{section}", None


# --- schedule --------------------------------------------------------------

def spread(n_slots, picks):
    """Indices for `picks` items spread evenly over n_slots positions."""
    return [int((i + 0.5) * n_slots / picks) for i in range(picks)]


def schedule(pins, week_start):
    """Sets pin['local'] (naive Atlantic datetime) on every pin."""
    outfits = [p for p in pins if p["type"] == "outfit"]
    outfits.sort(key=lambda p: not p["id"].startswith("gameday/"))   # stable
    per_day = max(OUTFITS_PER_DAY, -(-len(outfits) // 7))
    days = [[] for _ in range(7)]
    for i, p in enumerate(outfits):
        days[min(i // per_day, 6)].append(p)
    for p in (p for p in pins if p["type"] == "product"):
        min(days, key=len).append(p)        # earliest of the emptiest days

    window = (DAY_END_H - DAY_START_H) * 60
    for d, day_pins in enumerate(days):
        n = len(day_pins)
        if not n:
            continue
        # Outfit pins spread through the day, products in the gaps.
        o = [p for p in day_pins if p["type"] == "outfit"]
        rest = [p for p in day_pins if p["type"] != "outfit"]
        order = [None] * n
        for idx, p in zip(spread(n, len(o)) if o else [], o):
            order[idx] = p
        it = iter(rest)
        order = [p if p is not None else next(it) for p in order]
        for k, p in enumerate(order):
            mins = window * (k + 0.5) / n
            mins = round(mins / SLOT_MIN) * SLOT_MIN
            p["local"] = datetime.combine(week_start + timedelta(days=d),
                                          datetime.min.time()) + timedelta(hours=DAY_START_H, minutes=mins)
            p["utc"] = atlantic_to_utc(p["local"])
    return days


# --- live checks -----------------------------------------------------------

def http_status(url):
    for method in ("HEAD", "GET"):
        req = urllib.request.Request(url, headers=HEADERS, method=method)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return resp.status, resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            if e.code == 405 and method == "HEAD":
                continue
            return e.code, ""
        except Exception as e:      # DNS, timeout, TLS
            return f"error ({e.__class__.__name__}: {e})", ""
    return "error", ""


def check_live(pins, problems):
    urls = sorted({p["link"] for p in pins} | {p["media"] for p in pins})
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = dict(zip(urls, ex.map(http_status, urls)))
    for p in pins:
        label = f"{p['type']} {p['id']}"
        status, _ = results[p["link"]]
        if status != 200:
            problems.append(f"{label}: Link returned {status}: {p['link']}")
        status, ctype = results[p["media"]]
        if status != 200:
            problems.append(f"{label}: Media URL returned {status} (pushed yet?): {p['media']}")
        elif not ctype.startswith("image/"):
            problems.append(f"{label}: Media URL is {ctype or 'no content type'}, not an image: {p['media']}")


# --- validation ------------------------------------------------------------

REQUIRED = ("type", "id", "title", "description", "hashtags", "alt_text", "board", "section")


def validate(pins, settings, problems):
    boards = settings["boards"]
    seen = {}
    for p in pins:
        label = f"{p['type']} {p['id']}"
        title = p["title"].strip()
        if not title:
            problems.append(f"{label}: empty title")
        elif len(title) > MAX_TITLE:
            problems.append(f"{label}: title is {len(title)} chars, limit {MAX_TITLE}")
        bad_tags = [t for t in p["hashtags"] if not t.startswith("#") or len(t) < 2 or " " in t]
        if bad_tags:
            problems.append(f"{label}: bad hashtag(s) {bad_tags}")
        p["full_description"] = full_description(p, settings)
        n = len(p["full_description"])
        if n > MAX_DESC:
            fixed = n - len(p["description"].strip())
            problems.append(f"{label}: description is {n} chars with disclosure"
                            f"{' + AI line' if p['ai'] else ''} + hashtags, limit {MAX_DESC} "
                            f"({n - MAX_DESC} over; copy can be at most {MAX_DESC - fixed}, is {len(p['description'].strip())})")
        if p["board"] not in boards:
            problems.append(f"{label}: board {p['board']!r} isn't in pin_settings.json "
                            f"(Pinterest would create it)")
        elif p.get("section") and p["section"] not in boards[p["board"]]:
            problems.append(f"{label}: section {p['section']!r} isn't listed under {p['board']!r} "
                            f"in pin_settings.json (Pinterest would create it)")
        uncovered = p["retailers"] - set(settings["disclosure_retailers"])
        if uncovered:
            problems.append(f"{label}: no disclosure covers {', '.join(sorted(map(str, uncovered)))} "
                            f"(disclosure_retailers in pin_settings.json)")
        if p["has_amazon"] and "$" in title + p["description"]:
            problems.append(f"{label}: '$' in the copy of a pin with an Amazon item")
        for key, val in (("pin", (p["type"], p["id"])), ("Media URL", p["media"]),
                         ("title", title.casefold())):
            if (key, val) in seen:
                problems.append(f"{label}: duplicate {key} (also {seen[key, val]})")
            seen[key, val] = label


# --- output ----------------------------------------------------------------

def csv_rows(pins):
    rows = []
    for p in sorted(pins, key=lambda p: p["utc"]):
        board, _ = board_field(p)
        rows.append({
            "Title": p["title"].strip(),
            "Media URL": p["media"],
            "Pinterest board": board,
            "Thumbnail": "",
            "Description": p["full_description"],
            "Link": p["link"],
            "Publish date": p["utc"].strftime("%Y-%m-%dT%H:%M:%S"),
            "Keywords": ", ".join(p.get("keywords") or []),
        })
    return rows


def write_csvs(rows, batch):
    chunks = [rows[i:i + MAX_ROWS] for i in range(0, len(rows), MAX_ROWS)]
    paths = []
    for n, chunk in enumerate(chunks, 1):
        suffix = f"_{n}" if len(chunks) > 1 else ""
        path = os.path.join(PIN_DIR, f"pinterest_bulk_{batch}{suffix}.csv")
        with open(path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\r\n")
            w.writeheader()
            w.writerows(chunk)
        paths.append(path)
    return paths


def report(batch, days, pins, warnings, csv_paths):
    L = [f"# Pinterest bulk upload: {batch}", ""]
    if csv_paths:
        L += ["Files: " + ", ".join(os.path.relpath(p, REPO).replace("\\", "/") for p in csv_paths), ""]
    L += ["## Pins per day (Atlantic time)", "",
          "| Day | Outfit | Product | Total | Times |", "|---|---|---|---|---|"]
    for day_pins in days:
        if not day_pins:
            continue
        d = day_pins[0]["local"]
        times = ", ".join(p["local"].strftime("%H:%M") + (" O" if p["type"] == "outfit" else " P")
                          for p in sorted(day_pins, key=lambda p: p["local"]))
        no = sum(p["type"] == "outfit" for p in day_pins)
        L.append(f"| {d:%a %b} {d.day} | {no} | {len(day_pins) - no} | {len(day_pins)} | {times} |")
    L += [f"| **Total** | {sum(p['type'] == 'outfit' for p in pins)} | "
          f"{sum(p['type'] == 'product' for p in pins)} | {len(pins)} | |", ""]

    L += ["## Manual follow-ups", ""]
    unset = [(p, board_field(p)[1]) for p in pins if board_field(p)[1]]
    if unset:
        L += ["### Sections the CSV can't set",
              "These section names contain \"/\", which Pinterest's board column uses to "
              "separate board from section, so these pins go to the board only. Move them "
              "after upload, or rename the section without a \"/\" and list the new name "
              "in pin_settings.json.", ""]
        L += [f"- {p['title'].strip()} → {p['board']} › {s}" for p, s in unset] + [""]
    ai = [p for p in sorted(pins, key=lambda p: p["utc"]) if p["ai"]]
    if ai:
        L += ["### AI-modified label",
              "The CSV has no column for it. Add the label to each of these pins after "
              f"upload ({len(ai)}):", ""]
        L += [f"- {p['local']:%a %H:%M} — {p['title'].strip()}" for p in ai] + [""]
    L += ["### Alt text",
          "The CSV has no column for it. Paste after upload:", ""]
    L += [f"- {p['title'].strip()}: {p['alt_text'].strip()}"
          for p in sorted(pins, key=lambda p: p["utc"])] + [""]
    unchecked = [p for p in sorted(pins, key=lambda p: p["utc"]) if p.get("seller_unchecked")]
    if unchecked:
        L += ["### Unchecked SHEIN sellers",
              "Nobody has confirmed these products are sold by SHEIN rather than a "
              "third-party store. Check each before its publish time; for a marketplace "
              "one, delete the pin and run py -3 set_seller.py <id> marketplace "
              f"({len(unchecked)}):", ""]
        L += [f"- {p['local']:%a %H:%M} — {p['id']}" for p in unchecked] + [""]
    if warnings:
        L += ["## Warnings", ""] + [f"- {w}" for w in warnings] + [""]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("batch", help="batch date, e.g. oct-19 (reads pinterest/pins_<batch>.json)")
    ap.add_argument("--dry-run", action="store_true", help="validate and report, write nothing")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")    # titles carry emoji; cp1252 consoles can't

    settings = load_json(SETTINGS_JSON)
    data = load_json(os.path.join(PIN_DIR, f"pins_{args.batch}.json"))
    products = load_json(PRODUCTS_JSON)
    by_id = {p["id"]: p for p in products}

    problems, warnings = [], []
    try:
        week_start = date.fromisoformat(data["week_start"])
    except (KeyError, ValueError):
        sys.exit("pins file needs week_start as YYYY-MM-DD (the batch week's Monday)")
    if week_start.weekday() != 0:
        problems.append(f"week_start {week_start} is a {week_start:%A}, not a Monday")

    pins = []
    for i, p in enumerate(data.get("pins", []), 1):
        missing = [k for k in REQUIRED if k not in p]
        if missing:
            problems.append(f"pin #{i} ({p.get('id')}): missing {', '.join(missing)}")
            continue
        if resolve(p, products, by_id, settings, problems, warnings):
            pins.append(p)
    shein = [p for p in pins if p["type"] == "product" and p["shein_page"]]
    if shein and not any(p.get("price_pin") for p in shein):
        problems.append(f"none of the {len(shein)} SHEIN product pins has a product-pin.jpg: "
                        f"run py -3 make_product_pin.py --pick 20 --batch {args.batch} "
                        f"(and push the images) first")
    if not pins:
        problems.append("no usable pins")
    else:
        validate(pins, settings, problems)
        days = schedule(pins, week_start)
        now = datetime.now(timezone.utc)
        for p in pins:
            if p["utc"] <= now:
                problems.append(f"{p['type']} {p['id']}: publish time {p['local']:%a %b %d %H:%M} "
                                f"Atlantic is in the past")
        print(f"Checking {len({p['link'] for p in pins} | {p['media'] for p in pins})} URLs on the live site...")
        check_live(pins, problems)

    if problems:
        print(f"\n{len(problems)} problem(s), no CSV written:")
        for msg in problems:
            print(f"  - {msg}")
        for msg in warnings:
            print(f"  (warning) {msg}")
        sys.exit(1)

    csv_paths = [] if args.dry_run else write_csvs(csv_rows(pins), args.batch)
    text = report(args.batch, days, pins, warnings, csv_paths)
    if not args.dry_run:
        with open(os.path.join(PIN_DIR, f"pinterest_bulk_{args.batch}_report.md"), "w",
                  encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
