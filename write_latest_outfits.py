#!/usr/bin/env python3
"""
Writes the "Latest outfits" row on products/ (the hub-links nav under
the intro) from the newest outfit campaign pages, between
<!-- latest-outfits:start/end --> markers. Safe to re-run: the block is
replaced in place.

Usage:
    py -3 write_latest_outfits.py            (write/refresh the row)
    py -3 write_latest_outfits.py --check    (report only, change nothing)

The row links the newest campaign page in each outfit category, newest
first, LATEST_COUNT of them, labelled with the category name. A campaign
page is outfits/<category>/<campaign>/index.html that isn't a redirect
(retired campaign pages carry a meta refresh). Its date comes from the
slug (e.g. gameday-nov-23-8 -> Nov 23), in the year nearest the day the
page was first committed (today for a page not committed yet), so a
"jan-4" batch built in December reads as next year and old slugs don't
jump forward a year as time passes. When a category has several pages
for the same date (gameday-nov-23, gameday-nov-23-2, ...) the base page,
the one with no number suffix (else the lowest), is the one linked.
Pages whose slug has no month-day (the July "gameday-july24" style)
are never picked. Ties between categories on the same date follow
CATEGORY_ORDER.

Links are relative (../outfits/<category>/<campaign>/), i.e. the page's
canonical URL, trailing slash included.

Run it in the batch order after add_canonical.py and before
write_sitemap.py (it edits products/index.html, which moves its
<lastmod>). sync_catalog.py imports audit() from here (report item 18)
and fails when the block is missing or stale.
"""

import argparse
import datetime
import os
import re
import subprocess
import sys

from categories import CAMPAIGN_DATE_RE, added_from_campaign
from write_sitemap import _rel_glob, is_redirect

REPO = os.path.dirname(os.path.abspath(__file__))
PAGE = "products/index.html"
LATEST_COUNT = 5
# Tie-break order for campaigns on the same date (the order the row used
# when it was typed by hand); categories not listed follow, A-Z.
CATEGORY_ORDER = ["gameday", "casual", "date-night", "business-casual", "streetwear",
                  "night-out", "formal", "budget"]

START = "<!-- latest-outfits:start -->"
END = "<!-- latest-outfits:end -->"
BLOCK_RE = re.compile(r"([ \t]*)" + re.escape(START) + r".*?" + re.escape(END), re.DOTALL)
# The hand-typed row the first run replaces: the label line and the
# links line after it.
LEGACY_RE = re.compile(
    r'([ \t]*)<span class="hub-label">Latest outfits</span>[ \t]*\r?\n[ \t]*<a [^\n]*\r?\n')
SUFFIX_RE = re.compile(r"-\d{1,2}-(\d+)$")


def _abs(rel):
    return os.path.join(REPO, rel.replace("/", os.sep))


def first_commit_dates():
    """{path: YYYY-MM-DD of the commit that first added it}."""
    log = subprocess.run(
        ["git", "-c", "core.quotepath=off", "log", "--diff-filter=A", "--format=%x01%cs",
         "--name-only", "--no-renames", "--", "outfits"],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8", check=True).stdout
    first, date = {}, None
    for line in log.splitlines():
        if line.startswith("\x01"):
            date = line[1:]
        elif line and (line not in first or date < first[line]):
            first[line] = date
    return first


def campaigns():
    """[(date, category, campaign, rel)] for every dated, live campaign page."""
    first = first_commit_dates()
    today = datetime.date.today()
    out = []
    for rel in _rel_glob("outfits/*/*/index.html"):
        if is_redirect(rel):
            continue
        _, category, campaign, _ = rel.split("/")
        if not CAMPAIGN_DATE_RE.search(campaign):
            continue
        anchor = datetime.date.fromisoformat(first[rel]) if rel in first else today
        out.append((datetime.date.fromisoformat(added_from_campaign(campaign, anchor)),
                    category, campaign, rel))
    return out


def _order(category):
    return (CATEGORY_ORDER.index(category), "") if category in CATEGORY_ORDER \
        else (len(CATEGORY_ORDER), category)


def _suffix(campaign):
    m = SUFFIX_RE.search(campaign)
    return int(m.group(1)) if m else 0


def latest():
    """[(category, campaign)] for the row, newest first."""
    best = {}
    for date, category, campaign, _ in campaigns():
        key = (date, -_suffix(campaign))
        if category not in best or key > best[category][0]:
            best[category] = (key, campaign)
    ranked = sorted(best.items(), key=lambda kv: (-kv[1][0][0].toordinal(), _order(kv[0])))
    return [(category, campaign) for category, (_, campaign) in ranked[:LATEST_COUNT]]


def label(category):
    return " ".join(w.capitalize() for w in category.split("-"))


def expected_block(indent, nl):
    links = " ".join(f'<a href="../outfits/{c}/{s}/">{label(c)}</a>' for c, s in latest())
    return (f"{START}{nl}{indent}<span class=\"hub-label\">Latest outfits</span>{nl}"
            f"{indent}{links}{nl}{indent}{END}")


def _read():
    with open(_abs(PAGE), encoding="utf-8", newline="") as f:
        return f.read()


def _nl(text):
    return "\r\n" if "\r\n" in text else "\n"


def render(text):
    """(new page text, status): status is ok, stale or missing."""
    nl = _nl(text)
    m = BLOCK_RE.search(text)
    if m:
        indent = m.group(1)
        new = text[:m.start()] + indent + expected_block(indent, nl) + text[m.end():]
        return new, "ok" if new == text else "stale"
    m = LEGACY_RE.search(text)
    if m:
        indent = m.group(1)
        new = text[:m.start()] + indent + expected_block(indent, nl) + nl + text[m.end():]
        return new, "missing"
    return text, "missing"


def audit():
    """List of problems for sync_catalog.py report item 18 (empty = clean)."""
    _, status = render(_read())
    if status == "ok":
        return []
    return [f"{PAGE}: Latest outfits block {status} (run py -3 write_latest_outfits.py)"]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[1])
    ap.add_argument("--check", action="store_true", help="report only, change nothing")
    args = ap.parse_args()
    text = _read()
    new, status = render(text)
    for category, campaign in latest():
        print(f"  {label(category):<18} outfits/{category}/{campaign}/")
    if status == "ok":
        print(f"{PAGE}: Latest outfits row up to date.")
        return 0
    if new == text:
        print(f"{PAGE}: no Latest outfits row or block found to replace.")
        return 1
    if args.check:
        print(f"{PAGE}: Latest outfits block {status}.")
        return 1
    with open(_abs(PAGE), "w", encoding="utf-8", newline="") as f:
        f.write(new)
    print(f"{PAGE}: Latest outfits row written ({status} before).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
