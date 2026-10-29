#!/usr/bin/env python3
"""
Checks whether the SHEIN products in products.json are still listed,
and keeps data/dead_links.json (the products the Random Outfit Generator
leaves out) up to date. Never modifies products.json or any page. Meant
to run weekly via .github/workflows/affiliate-link-check.yml, which
commits data/dead_links.json when it changes and opens or updates a
single GitHub issue with the report.

Usage:
    python3 check_affiliate_links.py            (writes the report and data/dead_links.json)
    python3 check_affiliate_links.py --dry-run  (prints the report, writes nothing)

It NEVER requests an affiliate or tracking link (onelink.shein.com,
tidd.ly, awin1.com, Amazon): fetching one is exactly what a click is, so
every run would register as clicks on the site's affiliate links. The
first version of this script did that (it fetched each onelink and the
page it pointed to). Instead:

  - SHEIN: GET the plain ca.shein.com product page built from the
    record's goods_id (sellers.plain_url), following SHEIN's own
    redirects, never any affiliate parameters. Each goods_id is
    requested once, however many records share it.
  - Awin, Amazon: not checked. Their outbound URLs are tracking links
    and products.json has no plain product URL for them.

Gift guide cards (report only): every SHEIN tile on gift-guide/index.html
that no catalog record covers (no SHEIN record with that tile's link as
its outbound_url, or with that card as its holiday_pin) is checked too:
  - a card with a goods_id in gift-guide-shein-ids.json gets the same
    plain product-page check as a catalog product.
  - a card whose goods_id is null is "not covered, not requested": its
    only link is the affiliate link, which this script never requests.
    (A one-time capture on 2026-10-27 followed each card's onelink once
    to find its goods id, but every one stopped on onelink.shein.com, so
    the ids have to be looked up by hand on the SHEIN Affiliate site.)
  - a card whose shop link can't be read from the page is "not covered".
Card results go in the report's "Gift guide cards" section only, never in
data/dead_links.json or the exit code.

Results:
  - dead: HTTP 404/410, or SHEIN redirected the product URL somewhere
    that isn't that product's page (a delisted product goes to the
    homepage or a category).
  - ok: the request ended on the product's own page.
  - unknown: SHEIN's bot check (it redirects to /risk/challenge with
    HTTP 200), HTTP 403/429 or anything else unexpected, a timeout or
    connection error. Unknown is never counted as dead or as ok.

    SHEIN serves the bot check to plain HTTP requests most of the time,
    live and nonexistent goods ids alike (checked 2026-10-19), so most
    runs will be mostly unknown. After BOT_CHECK_LIMIT bot checks in a
    row the script stops requesting and marks the rest unknown, rather
    than keep hitting SHEIN for answers it won't give. It doesn't try to
    get past the bot check.

    Known limitation: a sold-out-but-still-listed product keeps its
    product URL, so it reads as ok. Stock status only renders after
    JavaScript runs.

data/dead_links.json is a list of {id, retailer, status, first_seen,
last_seen, consecutive}, one entry per product id whose last conclusive
result was dead (machine-written; don't edit by hand):
  - dead: consecutive + 1 and last_seen = today (or a new entry with
    consecutive 1). A rerun less than MIN_RUN_GAP_DAYS after last_seen
    doesn't count again, so two runs in one week can't confirm a link.
  - ok: the entry is removed.
  - unknown, or not checked (Amazon, Awin, a product no longer in
    products.json): the entry is left as it is.
  - an entry whose "note" starts with "manual:" was added by hand (e.g.
    a product page that says SOLD OUT, which this script reads as ok)
    and is never changed or removed by a run; delete it by hand when
    the product is back.
  status is "confirmed" once consecutive reaches CONFIRM_RUNS (dead in
  2 weekly runs with no ok in between), else "suspected". Only confirmed
  ids are left out of the outfit generator (confirmed_ids() below, used
  by outfit_generator.py; generator/index.html does the same).
"""

import argparse
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import gift_guide
from sellers import plain_url

REPO = os.path.dirname(os.path.abspath(__file__))
PRODUCTS_JSON = os.path.join(REPO, "products.json")
DEAD_LINKS_JSON = os.path.join(REPO, "data", "dead_links.json")
REPORT_PATH = os.path.join(REPO, "link_check_report.md")
GIFT_GUIDE_IDS_JSON = os.path.join(REPO, "gift-guide-shein-ids.json")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
TIMEOUT = 12
THROTTLE = 1.5
BOT_CHECK_LIMIT = 10   # stop requesting after this many bot checks in a row
CONFIRM_RUNS = 2       # dead in this many weekly runs = confirmed dead
MIN_RUN_GAP_DAYS = 6   # a rerun sooner than this doesn't count as another week


def load_dead_links(path=DEAD_LINKS_JSON):
    """data/dead_links.json entries, or [] if the file doesn't exist yet."""
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def confirmed_ids(entries=None):
    """Product ids confirmed dead (left out of the outfit generator)."""
    if entries is None:
        entries = load_dead_links()
    return {e["id"] for e in entries if e.get("status") == "confirmed"}


def get(url):
    """GET (never HEAD). Returns (status, final_url, error_or_None)."""
    req = urllib.request.Request(url, headers={"User-Agent": UA}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            resp.read()
            return resp.status, resp.geturl(), None
    except urllib.error.HTTPError as e:
        return e.code, url, None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return None, None, str(e)


def is_bot_check(final_url):
    path = urllib.parse.urlsplit(final_url or "").path.lower()
    return path.startswith("/risk/") or "captcha" in (final_url or "").lower()


def shein_verdict(status, final_url, err, goods_id):
    """(result, reason) for one plain SHEIN product-page request:
    result is "dead", "ok" or "unknown"."""
    if err is not None:
        low = err.lower()
        if "timed out" in low or "timeout" in low:
            return "unknown", "timeout"
        return "unknown", f"request error ({err[:80]})"
    if status in (404, 410):
        return "dead", f"HTTP {status}"
    if status in (403, 429):
        return "unknown", f"HTTP {status} (bot-blocked)"
    if not status or not 200 <= status < 300:
        return "unknown", f"unexpected HTTP {status}"
    parts = urllib.parse.urlsplit(final_url or "")
    host = (parts.hostname or "").lower()
    if not (host == "shein.com" or host.endswith(".shein.com")):
        return "unknown", f"ended outside shein.com ({host})"
    if is_bot_check(final_url):
        return "unknown", "SHEIN bot check"
    if f"-p-{goods_id}" in parts.path:
        return "ok", "product page"
    return "dead", f"redirected away from the product page: {parts.path[:80] or '/'}"


def update_dead_links(entries, results, retailers, today):
    """New dead_links.json entries from this run's results.

    entries: the current file's list. results: {id: "dead"|"ok"|"unknown"}
    for every id checked this run. retailers: {id: retailer}. today: a
    datetime.date. Returns the new list, sorted by id."""
    by_id = {e["id"]: dict(e) for e in entries}
    for pid, result in results.items():
        cur = by_id.get(pid)
        if cur is not None and str(cur.get("note", "")).startswith("manual:"):
            continue  # added by hand; runs never change it
        if result == "ok":
            by_id.pop(pid, None)
        elif result == "dead":
            if cur is None:
                by_id[pid] = {"id": pid, "retailer": retailers.get(pid, ""), "status": "suspected",
                              "first_seen": today.isoformat(), "last_seen": today.isoformat(),
                              "consecutive": 1}
            else:
                last = datetime.date.fromisoformat(cur["last_seen"])
                if (today - last).days >= MIN_RUN_GAP_DAYS:
                    cur["consecutive"] += 1
                    cur["last_seen"] = today.isoformat()
        # "unknown": leave the entry as it is.
    out = sorted(by_id.values(), key=lambda e: e["id"])
    for e in out:
        e["status"] = "confirmed" if e["consecutive"] >= CONFIRM_RUNS else "suspected"
    return out


def check_shein(products):
    """{goods_id: (result, reason)}, requesting each goods id once."""
    by_goods = {}
    for p in products:
        by_goods.setdefault(str(p["goods_id"]), p)
    out, bot_checks_in_row = {}, 0
    for i, (gid, p) in enumerate(by_goods.items(), 1):
        if bot_checks_in_row >= BOT_CHECK_LIMIT:
            out[gid] = ("unknown", f"not requested (SHEIN bot check on the previous {BOT_CHECK_LIMIT} requests)")
            continue
        status, final_url, err = get(plain_url(p))
        result, reason = shein_verdict(status, final_url, err, gid)
        bot_checks_in_row = bot_checks_in_row + 1 if reason == "SHEIN bot check" else 0
        out[gid] = (result, reason)
        print(f"[{i}/{len(by_goods)}] {result:8} {gid:>12} {reason[:80]}")
        time.sleep(THROTTLE)
    return out


def gift_guide_cards(shein):
    """The gift guide's SHEIN cards that no catalog record covers, each
    {card, name, link, goods_id}; and how many SHEIN cards there are."""
    links = {p.get("outbound_url") for p in shein}
    pins = {gift_guide.card_key(p["holiday_pin"]) for p in shein if p.get("holiday_pin")}
    ids = {}
    if os.path.isfile(GIFT_GUIDE_IDS_JSON):
        with open(GIFT_GUIDE_IDS_JSON, encoding="utf-8") as f:
            ids = {gift_guide.card_key(c["card"]): c.get("goods_id") for c in json.load(f)}
    cards = gift_guide.shein_cards()
    out = [dict(c, goods_id=ids.get(c["card"])) for c in cards
           if c["card"] not in pins and (c["link"] is None or c["link"] not in links)]
    return out, len(cards)


def write_report(rows, entries, skipped, path, cards=(), total_cards=0):
    by_result = {"dead": [], "ok": [], "unknown": []}
    for r in rows:
        by_result[r["result"]].append(r)
    names = {r["id"]: r["name"] for r in rows}
    confirmed = [e for e in entries if e["status"] == "confirmed"]
    suspected = [e for e in entries if e["status"] == "suspected"]

    by_id = [c for c in cards if c["how"] == "product page"]
    in_catalog = total_cards - len(cards)
    lines = [f"**Gift guide SHEIN cards checked: {in_catalog + len(by_id)} of {total_cards}** "
             f"({in_catalog} as catalog products, {len(by_id)} by goods id from "
             f"`gift-guide-shein-ids.json`; {len(cards) - len(by_id)} not covered).\n",
             f"_Checked {len(rows)} SHEIN products by their plain ca.shein.com product page "
             f"(never the affiliate link)._\n",
             f"- OK: {len(by_result['ok'])}",
             f"- Dead this run: {len(by_result['dead'])}",
             f"- Unknown (bot check, blocked or timed out; never counted): {len(by_result['unknown'])}",
             f"- Not checked: {', '.join(f'{n} {k}' for k, n in skipped.items()) or 'none'}\n",
             f"`data/dead_links.json`: {len(confirmed)} confirmed dead (left out of the outfit "
             f"generator), {len(suspected)} suspected (dead in 1 weekly run so far).\n"]

    def table(title, es):
        lines.append(f"## {title}\n")
        if not es:
            lines.append("None.\n")
            return
        lines.append("| Product | id | First seen | Last seen | Runs |")
        lines.append("|---|---|---|---|---|")
        for e in es:
            lines.append(f"| {names.get(e['id'], '(not in products.json)')} | `{e['id']}` | "
                         f"{e['first_seen']} | {e['last_seen']} | {e['consecutive']} |")
        lines.append("")

    table("Confirmed dead", confirmed)
    table("Suspected dead (needs one more dead run to confirm)", suspected)

    lines.append("## Dead this run\n")
    if by_result["dead"]:
        lines.append("| Product | id | Reason |")
        lines.append("|---|---|---|")
        for r in by_result["dead"]:
            lines.append(f"| {r['name']} | `{r['id']}` | {r['reason']} |")
    else:
        lines.append("None.")
    lines.append("")

    lines.append("## Unknown, by reason\n")
    reasons = {}
    for r in by_result["unknown"]:
        reasons[r["reason"]] = reasons.get(r["reason"], 0) + 1
    if reasons:
        for reason, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
            lines.append(f"- {n}: {reason}")
    else:
        lines.append("None.")
    lines.append("")

    lines.append("## Gift guide cards\n")
    lines.append("SHEIN cards on `gift-guide/index.html` with no `products.json` record. "
                 "Report only: they never go in `data/dead_links.json`.\n")
    if cards:
        label = {"ok": "OK", "dead": "**dead**", "unknown": "inconclusive"}
        lines.append("| Card | Product | Checked by | Result | Reason |")
        lines.append("|---|---|---|---|---|")
        for c in cards:
            if c["how"] == "not covered":
                lines.append(f"| {c['card']} | {c['name']} | — | **{c['label']}** | {c['reason']} |")
                continue
            lines.append(f"| {c['card']} | {c['name']} | goods id `{c['goods_id']}` | "
                         f"{label[c['result']]} | {c['reason']} |")
    else:
        lines.append("None.")
    lines.append("")

    text = "\n".join(lines)
    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    return text


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="print the report, write nothing")
    args = ap.parse_args()

    with open(PRODUCTS_JSON, encoding="utf-8") as f:
        products = json.load(f)

    shein = [p for p in products if p["retailer"] == "SHEIN" and p.get("goods_id")]
    checked = {p["id"] for p in shein}
    skipped = {}
    for p in products:
        if p["id"] not in checked:
            key = p["retailer"] if p["retailer"] != "SHEIN" else "SHEIN with no goods_id"
            skipped[key] = skipped.get(key, 0) + 1

    print(f"SHEIN products to check: {len(shein)} "
          f"({len({str(p['goods_id']) for p in shein})} unique goods ids)\n")
    by_goods = check_shein(shein)

    cards, total_cards = gift_guide_cards(shein)
    with_id = [c for c in cards if c["link"] and c["goods_id"]]
    print(f"\nGift guide SHEIN cards with no catalog record: {len(cards)} of {total_cards} "
          f"({len(with_id)} with a goods id)\n")
    by_card_goods = check_shein([{"goods_id": c["goods_id"], "name": c["name"]} for c in with_id])
    for c in cards:
        if not c["link"]:
            c.update(how="not covered", label="not covered",
                     reason="shop link can't be read from the page")
        elif c["goods_id"]:
            result, reason = by_card_goods[str(c["goods_id"])]
            c.update(how="product page", result=result, reason=reason)
        else:
            c.update(how="not covered", label="not covered, not requested",
                     reason="no goods id in `gift-guide-shein-ids.json` (the affiliate link is never requested)")

    rows = []
    for p in shein:
        result, reason = by_goods[str(p["goods_id"])]
        rows.append({"id": p["id"], "name": p["name"], "result": result, "reason": reason})

    entries = update_dead_links(load_dead_links(), {r["id"]: r["result"] for r in rows},
                                {p["id"]: p["retailer"] for p in shein},
                                datetime.datetime.now(datetime.timezone.utc).date())
    report = write_report(rows, entries, skipped, None if args.dry_run else REPORT_PATH,
                          cards, total_cards)

    if args.dry_run:
        print("\n" + report)
        return
    os.makedirs(os.path.dirname(DEAD_LINKS_JSON), exist_ok=True)
    with open(DEAD_LINKS_JSON, "w", encoding="utf-8", newline="\n") as f:
        json.dump(entries, f, indent=2)
        f.write("\n")
    counts = {k: sum(r["result"] == k for r in rows) for k in ("ok", "dead", "unknown")}
    print(f"\nOK: {counts['ok']}  DEAD: {counts['dead']}  UNKNOWN: {counts['unknown']}")
    print(f"Confirmed dead: {len(confirmed_ids(entries))}")
    print(f"Report written to {REPORT_PATH}; dead links to {DEAD_LINKS_JSON}")
    sys.exit(1 if counts["dead"] else 0)


if __name__ == "__main__":
    main()
