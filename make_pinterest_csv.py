#!/usr/bin/env python3
"""
Builds the weekly Pinterest bulk-upload CSV from a batch's pin copy.

Usage:
    py -3 make_pinterest_csv.py oct-19             (reads pinterest/pins_oct-19.json)
    py -3 make_pinterest_csv.py oct-19 --dry-run   (validate + report, write nothing)
    py -3 make_pinterest_csv.py oct-19 --unpushed-media   (see below)

Inputs (all in pinterest/):
    pins_<batch>.json   one entry per pin, copy supplied by hand:
        {"batch": "oct-19", "week_start": "2026-10-19", "pins": [
          {"type": "outfit", "id": "gameday/gameday-oct-19", ...},
          {"type": "product", "id": "trending-products/trending-products-oct-19-3/polo", ...}]}
      Every pin has title, description, hashtags (list, each starting
      with #), alt_text, board and section ("" for none); keywords (list)
      is optional. An outfit id is its folder under outfits/; a product
      id is its products.json id; a gift id is an Amazon card's data-id on
      gift-guide/index.html (type "gift", for cards with no product page
      of their own). week_start is the batch week's Monday; a batch that
      runs on other dates gives start_date instead (its 7 days start there).
      Optional per pin: "publish" ("YYYY-MM-DDTHH:MM", Atlantic) fixes its
      time instead of the automatic schedule (still inside the 7 days and
      the 10:00-23:00 window); "hold" (a reason) validates and schedules
      the pin but leaves its row out of the CSV, listed in the report.
      Optional per batch: "hashtags_first": true puts the hashtags right
      after the copy, before the disclosure and AI line.
      Section routing: for batches from pin_settings.json
      routing.applies_from on, pin_routing.py may move a pin's board/
      section into a thin section (price tiers, basics, running, 1 in 3
      Game Day outfits to Men's Stadium Streetwear); the report lists every
      move and the thin-section counts. "section_locked": true on a pin
      keeps its hand-set board/section; "outfit_check": true marks the
      weekly Stadium Streetwear Outfit Check (always Men's Stadium
      Streetwear).
    pin_settings.json   the disclosure appended to every description
      (disclosure_shein_only when every item in the pin is SHEIN; with
      any Awin item, the line naming only the partners present:
      disclosure_awin_only, _awin_amazon, _awin_shein or disclosure_awin
      for all three; the wording names House of Blanks, and a pin whose
      Awin items are another merchant gets that merchant's name instead,
      which must be listed in awin_merchants); else disclosure; a pin with a retailer
      outside disclosure_retailers is an error), the AI line added for AI-image pins (every outfit pin, and product
      pins whose retailer is in ai_image_retailers, unless the record
      says "ai_image": false), and the account's
      boards with their sections. Pinterest CREATES any board or section
      named in the CSV that doesn't exist, so these must match the
      account exactly; anything not listed is an error.

Per pin:
    Link        the outfit or product page on the live site, with UTM
                tags for batches starting on or after UTM_FROM (see
                utm_link): utm_source=pinterest, utm_medium=social,
                utm_campaign=<batch start date, YYYY-MM-DD>,
                utm_content=<campaign slug>-<item slug, or "outfit">
                (gift pins: gift-guide-<card id>), utm_term=<pin type>.
                Only links on SITE get them; a link that leaves the site
                (Amazon, SHEIN, Awin) never does, and validate_utm makes
                either mistake a problem.
    Media URL   outfit-pin.jpg / product-pin.jpg (falls back to
                outfit-preview.jpg with a warning, or the product photo
                for products make_product_pin.py --pick didn't choose).
                A gift pin uses holiday-2026/pins/<id>_gift.jpg (see
                make_gift_pin.py), <id>_holiday.png, or <id>_ai.jpg: AI
                images, never the Amazon product photo. The one
                exception: a card whose record has "ai_image": false
                (the team-licensed N184/N189, real photo with the logo)
                uses <id>_photo.jpg (make_gift_pin.py --real) and gets
                no AI line or AI-modified label.
                Its Link is the product page of the products.json id in
                its optional "page" field, else the card's own anchor on
                the gift guide (gift-guide/#<id>). A product pin of a
                gift guide listing record links to its card the same way
                (gift-guide/#<holiday_pin>) when the page has that id.
                A batch where no SHEIN product pin has a product-pin.jpg
                is an error: make_product_pin.py wasn't run.
    Description copy + disclosure [+ AI line] + hashtags.
    Board       "Board/Section". A section whose own name contains "/"
                can't be expressed that way, so those pins get the board
                only and the report lists them to move by hand.

Schedule: across week_start's Mon-Sun, outfit pins 2 a day (gameday
first, then file order; over 14 they spread evenly across all 7 days),
product and gift pins each onto the day with the fewest pins so far, every day's pins spread evenly between 10:00 and 23:00
Atlantic time (9 am-10 pm Eastern), written in UTC (Pinterest reads
Publish date as UTC). DAY_END_H stays below 24 so no slot lands on the
next day's 00:00. Pins scheduled by hand or by any other script
(gift guide, holiday) use the same window.

Validation runs before anything is written; on any problem the script
lists them all and writes no CSV: Link and Media URL must return 200 on
the live site (so push the pin images first), title <= 100 and full
description <= 500 characters (Pinterest's limits), boards/sections in
pin_settings.json, no duplicate pins/images/titles, no publish time in
the past, no "$" in the copy of a pin with an Amazon item (Amazon
prices can't be shown), no bare "$" (one not preceded by "CA") in the
title, description or alt text of a pin with a SHEIN item (SHEIN prices
are CAD, so they read CA$; only a warning in the report for a batch
starting before CAD_COPY_FROM, whose pins are already uploaded), no
product pin of a SHEIN product whose seller is "marketplace" (a
third-party store; see sellers.py). Product pins whose seller is still
"unchecked" go through, listed in the report.

--unpushed-media turns a Media URL that isn't live yet but exists in the
repo into a warning, so a CSV can go in a PR with its new images. Rebuild
without it after the merge, before uploading.

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
import posixpath
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import gift_guide
import pin_routing
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
DAY_START_H, DAY_END_H = 10, 23     # Atlantic time; end < 24 (no next-day 00:00)
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


def card_anchor(card_id):
    """The gift guide element id for a card ("N106"), or None when the
    page has no element with that id."""
    if not card_id:
        return None
    with open(os.path.join(REPO, gift_guide.PAGE), encoding="utf-8") as f:
        return card_id if f'id="{card_id}"' in f.read() else None


def gift_card(card_id):
    """(section id, retailer class) of a gift guide card, or None."""
    with open(os.path.join(REPO, gift_guide.PAGE), encoding="utf-8") as f:
        page = f.read()
    at = page.find(f'data-id="{card_id}"')
    if at < 0:
        return None
    section = re.findall(r'<section class="section tier" id="([^"]+)"', page[:at])
    retailer = re.search(r'class="retailer (\w+)"', page[at:])
    return (section[-1] if section else None), (retailer.group(1) if retailer else None)


def gift_record(products, card_id):
    """The gift guide listing record for a card: the one whose holiday_pin
    names it, else the one whose tile image is gift-guide/img/<card>_...
    None when no record matches."""
    key = gift_guide.card_key(card_id)
    for p in products:
        if gift_guide.listing_only(p) and gift_guide.card_key(p.get("holiday_pin") or "") == key:
            return p
    for p in products:
        m = re.match(r"gift-guide/img/([A-Za-z]+\d+)_", p.get("image") or "")
        if gift_guide.listing_only(p) and m and gift_guide.card_key(m.group(1)) == key:
            return p
    return None


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
        with open(os.path.join(REPO, rel, "index.html"), encoding="utf-8") as f:
            cards = re.findall(r'<a class="card" href="([^"]+)"', f.read())
        # A card can link to a page in another outfit's folder: go by the
        # cards, not the folder, or that item's retailer goes undisclosed.
        items, missing = gift_guide.card_records(rel, cards, products)
        if missing:
            problems.append(f"{label}: {len(missing)} card(s) with no products.json record")
            return False
        pin["retailers"] = {p.get("retailer") for p in items}
        pin["has_amazon"] = "Amazon" in pin["retailers"]
        pin["items"] = items
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
        if gift_guide.listing_only(rec) and card_anchor(rec.get("holiday_pin")):
            # Land on the listing's own card, as gift pins do.
            pin["link"] += "#" + card_anchor(rec["holiday_pin"])
        # "ai_image": false on a record marks a real retailer photo used in
        # place of the AI image (e.g. when Gemini got the product wrong).
        pin["ai"] = rec.get("ai_image",
                            rec.get("retailer") in settings.get("ai_image_retailers", []))
        pin["retailers"] = {rec.get("retailer")}
        pin["has_amazon"] = rec.get("retailer") == "Amazon"
        pin["rec"], pin["items"] = rec, [rec]
        return True

    if pin.get("type") == "gift":
        card = gift_card(pin["id"])
        if card is None or not card[0]:
            problems.append(f"{label}: no card with that data-id in a gift guide price section")
            return False
        if card[1] != "amazon":
            problems.append(f"{label}: gift pins are for Amazon cards (this one is {card[1]})")
            return False
        # A card whose record says "ai_image": false shows the real product
        # photo (Jesse's call for team-licensed items, logo visible). Its
        # pin uses <id>_photo.jpg (make_gift_pin.py --real) and carries no
        # AI line; every other gift pin must use an AI image.
        rec = gift_record(products, pin["id"])
        real = rec is not None and rec.get("ai_image") is False
        names = ((f"{pin['id']}_photo.jpg",) if real else
                 (f"{pin['id']}_gift.jpg", f"{pin['id']}_holiday.png", f"{pin['id']}_ai.jpg"))
        for name in names:
            if os.path.isfile(os.path.join(REPO, gift_guide.PIN_DIR, name)):
                break
        else:
            kind = f"real-photo pin image ({names[0]})" if real else "AI pin image"
            problems.append(f"{label}: no {kind} in {gift_guide.PIN_DIR}")
            return False
        pin["media"] = f"{SITE}{gift_guide.PIN_DIR}/{name}"
        pin["link"] = f"{SITE}gift-guide/#{pin['id']}"
        if pin.get("page"):
            rec = by_id.get(pin["page"])
            if rec is None:
                problems.append(f"{label}: page {pin['page']} isn't in products.json")
                return False
            pin["link"] = page_url(os.path.dirname(rec["detail_page_url"]))
        pin["ai"] = not real
        pin["retailers"] = {"Amazon"}
        pin["has_amazon"] = True
        return True

    problems.append(f"{label}: type must be 'outfit', 'product' or 'gift'")
    return False


# --- UTM tags --------------------------------------------------------------

# First batch whose hub links carry UTM tags. Batches before it are already
# uploaded and scheduled on Pinterest: rebuilding one keeps its plain links.
UTM_FROM = date(2026, 11, 23)
UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term")
# Hosts a pin Link must never tag: the retailers and affiliate networks.
AFFILIATE_HOSTS = ("amazon.", "amzn.to", "amzn.", "shein.", "awin1.com", "awin.com")


def slug(text):
    """Lowercase, hyphens only: 'Gameday Nov_23' -> 'gameday-nov-23'."""
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")


def utm_content(pin):
    """<campaign slug>-<item slug or "outfit">; gift pins gift-guide-<card id>."""
    parts = [s for s in pin["id"].strip("/").split("/") if s]
    if pin["type"] == "outfit":
        return slug(f"{parts[-1]}-outfit")
    if pin["type"] == "gift":
        return slug(f"gift-guide-{pin['id']}")
    return slug("-".join(parts[-2:]))


def utm_params(pin, campaign):
    return {"utm_source": "pinterest", "utm_medium": "social",
            "utm_campaign": campaign, "utm_content": utm_content(pin),
            "utm_term": pin["type"]}


def is_hub(url):
    return url.startswith(SITE)


def is_affiliate(url):
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    return any(h in host for h in AFFILIATE_HOSTS)


def add_query(url, params):
    """url with params added to its query (replacing any of the same name),
    the fragment kept after the query: .../gift-guide/?utm_...#N163."""
    parts = urllib.parse.urlsplit(url)
    query = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
             if k not in params]
    query += list(params.items())
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))


def utm_link(pin, campaign):
    """The pin's Link with UTM tags if it's a hub page; any other link as is."""
    if not is_hub(pin["link"]):
        return pin["link"]
    return add_query(pin["link"], utm_params(pin, campaign))


def validate_utm(pins, campaign, problems, tagged=True):
    """A hub Link without the expected UTM tags (when this batch is tagged)
    or any non-hub Link carrying utm_* is a problem."""
    for p in pins:
        label = f"{p['type']} {p['id']}"
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(p["link"]).query))
        has = {k for k in query if k.startswith("utm_")}
        if not is_hub(p["link"]):
            if has:
                kind = "affiliate" if is_affiliate(p["link"]) else "off-site"
                problems.append(f"{label}: {kind} Link carries UTM tags ({', '.join(sorted(has))}): "
                                f"{p['link']}")
            continue
        if not tagged:
            continue
        want = utm_params(p, campaign)
        wrong = [k for k, v in want.items() if query.get(k) != v]
        if wrong:
            problems.append(f"{label}: hub Link missing or wrong {', '.join(wrong)}: {p['link']}")
        if len(p["link"]) > 500:
            problems.append(f"{label}: Link is {len(p['link'])} chars (keep it well under "
                            f"Pinterest's 2,048)")


def disclosure(pin, settings):
    """The SHEIN-only wording for a pin whose items are all SHEIN; with
    any Awin item, the line naming only the partners present; else the
    full one (SHEIN + Amazon)."""
    retailers = pin["retailers"]
    if retailers == {"SHEIN"}:
        return settings["disclosure_shein_only"].strip()
    if "Awin" in retailers:
        key = {frozenset({"Awin"}): "disclosure_awin_only",
               frozenset({"Awin", "Amazon"}): "disclosure_awin_amazon",
               frozenset({"Awin", "SHEIN"}): "disclosure_awin_shein"}.get(frozenset(retailers), "disclosure_awin")
        # The awin lines name House of Blanks; swap in the Awin merchants
        # actually in the pin (e.g. "As a Moosehill affiliate, ...").
        names = awin_merchants(pin)
        line = settings[key].strip()
        if names and names != [AWIN_DEFAULT_MERCHANT]:
            line = line.replace(AWIN_DEFAULT_MERCHANT, " and ".join(names))
        return line
    return settings["disclosure"].strip()


# The merchant the disclosure_awin* lines in pin_settings.json name.
AWIN_DEFAULT_MERCHANT = "House of Blanks"


def awin_merchants(pin):
    """Sorted merchant names of the pin's Awin items ("?" when a record
    has none, so it fails the awin_merchants check)."""
    return sorted({i.get("merchant") or "?" for i in pin.get("items", [])
                   if i.get("retailer") == "Awin"})


def full_description(pin, settings):
    tags = [" ".join(pin["hashtags"])] if pin["hashtags"] else []
    parts = [pin["description"].strip()]
    if pin.get("hashtags_first"):
        parts += tags
    parts.append(disclosure(pin, settings))
    if pin["ai"]:
        parts.append(settings["ai_line"].strip())
    if not pin.get("hashtags_first"):
        parts += tags
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


def schedule(pins, week_start, problems=None):
    """Sets pin['local'] (naive Atlantic datetime) on every pin. A pin with
    "publish" ("YYYY-MM-DDTHH:MM", Atlantic) keeps that time; it must fall in
    the batch's 7 days and the DAY_START_H-DAY_END_H window."""
    problems = problems if problems is not None else []
    days = [[] for _ in range(7)]
    fixed = [p for p in pins if p.get("publish")]
    for p in fixed:
        try:
            local = datetime.fromisoformat(p["publish"])
        except ValueError:
            problems.append(f"{p['type']} {p['id']}: publish {p['publish']!r} isn't YYYY-MM-DDTHH:MM")
            local = datetime.combine(week_start, datetime.min.time()) + timedelta(hours=DAY_START_H)
        d = (local.date() - week_start).days
        if not 0 <= d < 7:
            problems.append(f"{p['type']} {p['id']}: publish {local:%Y-%m-%d} is outside the batch's 7 days")
            d = min(max(d, 0), 6)
        if not (DAY_START_H * 60 <= local.hour * 60 + local.minute <= DAY_END_H * 60):
            problems.append(f"{p['type']} {p['id']}: publish {local:%H:%M} is outside "
                            f"{DAY_START_H:02d}:00-{DAY_END_H:02d}:00 Atlantic")
        p["local"], p["utc"] = local, atlantic_to_utc(local)
        days[d].append(p)
    rest_pins = [p for p in pins if not p.get("publish")]
    outfits = [p for p in rest_pins if p["type"] == "outfit"]
    outfits.sort(key=lambda p: not p["id"].startswith("gameday/"))   # stable
    for i, p in enumerate(outfits):
        if len(outfits) > 7 * OUTFITS_PER_DAY:
            days[i * 7 // len(outfits)].append(p)
        else:
            days[i // OUTFITS_PER_DAY].append(p)
    for p in (p for p in rest_pins if p["type"] != "outfit"):
        min(days, key=len).append(p)        # earliest of the emptiest days

    window = (DAY_END_H - DAY_START_H) * 60
    for d, all_day_pins in enumerate(days):
        day_pins = [p for p in all_day_pins if not p.get("publish")]
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


def check_live(pins, problems, warnings, unpushed_media=False):
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
            if unpushed_media and os.path.isfile(os.path.join(REPO, p["media"][len(SITE):])):
                warnings.append(f"{label}: Media URL not live yet: {p['media']}")
                continue
            problems.append(f"{label}: Media URL returned {status} (pushed yet?): {p['media']}")
        elif not ctype.startswith("image/"):
            problems.append(f"{label}: Media URL is {ctype or 'no content type'}, not an image: {p['media']}")


# --- validation ------------------------------------------------------------

REQUIRED = ("type", "id", "title", "description", "hashtags", "alt_text", "board", "section")
BARE_DOLLAR = re.compile(r"(?<!CA)\$")
CAD_COPY_FROM = date(2026, 11, 9)   # first batch held to CA$ in its pin copy


def validate(pins, settings, problems, warnings, week_start):
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
        unknown = [m for m in awin_merchants(p) if m not in settings.get("awin_merchants", [AWIN_DEFAULT_MERCHANT])]
        if unknown:
            problems.append(f"{label}: Awin merchant {', '.join(unknown)} isn't in awin_merchants "
                            f"in pin_settings.json (the disclosure would name the wrong partner)")
        if p["has_amazon"] and "$" in title + p["description"]:
            problems.append(f"{label}: '$' in the copy of a pin with an Amazon item")
        if "SHEIN" in p["retailers"]:
            bare = [k for k in ("title", "description", "alt_text") if BARE_DOLLAR.search(p[k])]
            if bare:
                listed = problems if week_start >= CAD_COPY_FROM else warnings
                listed.append(f"{label}: bare '$' in the {', '.join(bare)} of a pin with a "
                              f"SHEIN item (SHEIN prices are CAD: write CA$)")
        for key, val in (("pin", (p["type"], p["id"])), ("Media URL", p["media"]),
                         ("title", title.casefold())):
            if (key, val) in seen:
                problems.append(f"{label}: duplicate {key} (also {seen[key, val]})")
            seen[key, val] = label


# --- output ----------------------------------------------------------------

def csv_rows(pins):
    rows = []
    for p in sorted((p for p in pins if not p.get("hold")), key=lambda p: p["utc"]):
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


def report(batch, days, pins, warnings, csv_paths, routing_lines=()):
    L = [f"# Pinterest bulk upload: {batch}", ""]
    if csv_paths:
        L += ["Files: " + ", ".join(os.path.relpath(p, REPO).replace("\\", "/") for p in csv_paths), ""]
    L += ["## Pins per day (Atlantic time)", "",
          "| Day | Outfit | Product | Gift | Total | Times |", "|---|---|---|---|---|---|"]
    for day_pins in days:
        if not day_pins:
            continue
        d = day_pins[0]["local"]
        times = ", ".join(p["local"].strftime("%H:%M") + " " + p["type"][0].upper()
                          for p in sorted(day_pins, key=lambda p: p["local"]))
        n = {t: sum(p["type"] == t for p in day_pins) for t in ("outfit", "product", "gift")}
        L.append(f"| {d:%a %b} {d.day} | {n['outfit']} | {n['product']} | {n['gift']} | "
                 f"{len(day_pins)} | {times} |")
    L += [f"| **Total** | {sum(p['type'] == 'outfit' for p in pins)} | "
          f"{sum(p['type'] == 'product' for p in pins)} | "
          f"{sum(p['type'] == 'gift' for p in pins)} | {len(pins)} | |", ""]

    counts = {}
    for p in pins:
        key = (p["board"], (p.get("section") or "").strip())
        counts[key] = counts.get(key, 0) + 1
    L += ["## Boards and sections", "", "| Board | Section | Pins |", "|---|---|---|"]
    L += [f"| {b} | {s or '(none)'} | {n} |" for (b, s), n in sorted(counts.items())] + [""]
    L += list(routing_lines)

    L += ["## Manual follow-ups", ""]
    held = [p for p in sorted(pins, key=lambda p: p["utc"]) if p.get("hold")]
    if held:
        L += ["### Held pins (validated, NOT in the CSV)",
              "Their row is left out of the upload CSV. Add it (or rebuild without "
              f"\"hold\") once the issue is fixed ({len(held)}):", ""]
        L += [f"- {p['local']:%a %b} {p['local'].day} {p['local']:%H:%M} — {p['id']} — "
              f"{p['title'].strip()}: {p['hold']}" for p in held] + [""]
    unset =[(p, board_field(p)[1]) for p in pins if board_field(p)[1]]
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
        L += [f"- {p['local']:%a %H:%M} — {p['title'].strip()}"
              + (" (also tick: includes an AI-generated person)" if p["type"] == "outfit" else "")
              for p in ai] + [""]
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
    ap.add_argument("--unpushed-media", action="store_true",
                    help="a Media URL not live yet but in the repo is a warning, not a problem")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")    # titles carry emoji; cp1252 consoles can't

    settings = load_json(SETTINGS_JSON)
    data = load_json(os.path.join(PIN_DIR, f"pins_{args.batch}.json"))
    products = load_json(PRODUCTS_JSON)
    by_id = {p["id"]: p for p in products}

    problems, warnings = [], []
    try:
        week_start = date.fromisoformat(data.get("start_date") or data["week_start"])
    except (KeyError, ValueError):
        sys.exit("pins file needs week_start as YYYY-MM-DD (the batch week's Monday)")
    if week_start.weekday() != 0 and not data.get("start_date"):
        problems.append(f"week_start {week_start} is a {week_start:%A}, not a Monday")

    pins = []
    for i, p in enumerate(data.get("pins", []), 1):
        missing = [k for k in REQUIRED if k not in p]
        if missing:
            problems.append(f"pin #{i} ({p.get('id')}): missing {', '.join(missing)}")
            continue
        if resolve(p, products, by_id, settings, problems, warnings):
            p["hashtags_first"] = bool(data.get("hashtags_first"))
            pins.append(p)
    shein = [p for p in pins if p["type"] == "product" and p["shein_page"]]
    if shein and not any(p.get("price_pin") for p in shein):
        problems.append(f"none of the {len(shein)} SHEIN product pins has a product-pin.jpg: "
                        f"run py -3 make_product_pin.py --pick 20 --batch {args.batch} "
                        f"(and push the images) first")
    campaign = week_start.isoformat()
    tagged = week_start >= UTM_FROM
    if tagged:
        for p in pins:
            p["link"] = utm_link(p, campaign)
    routing_lines = []
    if pins and "routing" in settings:
        # Thin-section routing (pin_routing.py): moves pins for batches from
        # routing.applies_from on, only suggests for earlier ones.
        applied = week_start >= date.fromisoformat(settings["routing"]["applies_from"])
        before = pin_routing.current_counts(settings["routing"], exclude_batch=args.batch)
        after = dict(before)
        decisions = pin_routing.route(pins, settings, after, apply=applied)
        warnings += pin_routing.warnings_from(decisions)
        routing_lines = pin_routing.report_lines(pins, settings, before, after, decisions, applied)
        print("Thin sections this batch (before + this batch = after, target "
              f"{settings['routing']['thin']['target']}):")
        for key in pin_routing.thin_keys(settings["routing"]):
            print(f"  {pin_routing.fmt(key)}: {before[key]} + {after[key] - before[key]} = {after[key]}")
    if not pins:
        problems.append("no usable pins")
    else:
        validate(pins, settings, problems, warnings, week_start)
        validate_utm(pins, campaign, problems, tagged)
        days = schedule(pins, week_start, problems)
        now = datetime.now(timezone.utc)
        for p in pins:
            if p["utc"] <= now:
                problems.append(f"{p['type']} {p['id']}: publish time {p['local']:%a %b %d %H:%M} "
                                f"Atlantic is in the past")
        print(f"Checking {len({p['link'] for p in pins} | {p['media'] for p in pins})} URLs on the live site...")
        check_live(pins, problems, warnings, args.unpushed_media)

    if problems:
        print(f"\n{len(problems)} problem(s), no CSV written:")
        for msg in problems:
            print(f"  - {msg}")
        for msg in warnings:
            print(f"  (warning) {msg}")
        sys.exit(1)

    csv_paths = [] if args.dry_run else write_csvs(csv_rows(pins), args.batch)
    text = report(args.batch, days, pins, warnings, csv_paths, routing_lines)
    if not args.dry_run:
        with open(os.path.join(PIN_DIR, f"pinterest_bulk_{args.batch}_report.md"), "w",
                  encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
