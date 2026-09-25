#!/usr/bin/env python3
"""
Writes sitemap.xml at the repo root.

Usage:
    python write_sitemap.py            (write sitemap.xml if it changed)
    python write_sitemap.py --check    (report only, change nothing)

Included:
  - The homepage and the shop grid (products/)
  - The outfits/ and videos/ hubs and every category page under them
  - Every campaign page (outfits/<theme>/<campaign>/,
    videos/<category>/<campaign>/), legacy link-list pages included
  - Every product detail page listed in products.json

Excluded:
  - Redirect pages: anything with a meta refresh, which covers the root
    redirect-stub folders (they're outside outfits/ and videos/ anyway)
    and retired campaign pages like videos/other/this-or-that-aug-14/.
    Detected from the page itself, so a newly retired page drops out
    without editing this script.
  - archive/ (a list of links to the root redirect stubs, not worth
    indexing) and everything that isn't a page.

<lastmod> is the date (YYYY-MM-DD) of the last git commit that touched
the page's file. products.json has no date field, and the date in a
campaign slug is when it was published, not when the page last changed.
The shop grid (products/) takes the later of products/index.html and
products.json, since it renders from the latter. A file with uncommitted
changes gets today's date. In the weekly batch this runs before the
commit, so new pages get the batch date, which is also their commit
date, and a later re-run produces the same file.

No <changefreq> or <priority>: Google ignores both.

This is a GitHub Pages project site, so there's no robots.txt at the
domain root to advertise the sitemap from. Submit
https://thatfootball12.github.io/thatfootball12-links/sitemap.xml in
Google Search Console instead.

sync_catalog.py imports expected_urls() and sitemap_urls() from here to
report pages missing from sitemap.xml and entries whose page is gone.
"""

import argparse
import datetime
import glob
import json
import os
import re
import subprocess
from xml.sax.saxutils import escape

REPO = os.path.dirname(os.path.abspath(__file__))
PRODUCTS_JSON = os.path.join(REPO, "products.json")
SITEMAP = os.path.join(REPO, "sitemap.xml")
SITE = "https://thatfootball12.github.io/thatfootball12-links/"

REFRESH_RE = re.compile(r'http-equiv="refresh"', re.I)
LOC_RE = re.compile(r"<loc>([^<]+)</loc>")


def _abs(rel):
    return os.path.join(REPO, rel.replace("/", os.sep))


def _rel_glob(pattern):
    return sorted(os.path.relpath(p, REPO).replace(os.sep, "/")
                  for p in glob.glob(os.path.join(REPO, pattern)))


def is_redirect(rel):
    with open(_abs(rel), encoding="utf-8", errors="replace") as f:
        return bool(REFRESH_RE.search(f.read()))


def url_for(rel):
    return SITE + re.sub(r"index\.html$", "", rel)


def page_for(url):
    """Repo-relative index.html path for a sitemap URL (None if off-site)."""
    if not url.startswith(SITE):
        return None
    return url[len(SITE):] + "index.html"


def expected_urls():
    """Ordered list of (url, [source files whose last change sets lastmod])."""
    entries = [
        ("index.html", ["index.html"]),
        ("products/index.html", ["products/index.html", "products.json"]),
    ]
    for rel in ["outfits/index.html", "videos/index.html"] + \
            _rel_glob("outfits/*/index.html") + _rel_glob("videos/*/index.html"):
        entries.append((rel, [rel]))
    for rel in _rel_glob("outfits/*/*/index.html") + _rel_glob("videos/*/*/index.html"):
        if not is_redirect(rel):
            entries.append((rel, [rel]))
    with open(PRODUCTS_JSON, encoding="utf-8") as f:
        products = json.load(f)
    for rel in sorted(p["detail_page_url"] for p in products):
        if os.path.isfile(_abs(rel)) and not is_redirect(rel):
            entries.append((rel, [rel]))
    return [(url_for(rel), srcs) for rel, srcs in entries]


def _git_dates():
    """{path: YYYY-MM-DD of the latest commit touching it}, and the set of
    paths with uncommitted changes."""
    log = subprocess.run(
        ["git", "-c", "core.quotepath=off", "log", "--format=%x01%cs", "--name-only", "--no-renames"],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8", check=True).stdout
    last, date = {}, None
    for line in log.splitlines():
        if line.startswith("\x01"):
            date = line[1:]
        elif line and (line not in last or date > last[line]):
            last[line] = date
    status = subprocess.run(
        ["git", "-c", "core.quotepath=off", "status", "--porcelain", "--untracked-files=all"],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8", check=True).stdout
    dirty = {line[3:].split(" -> ")[-1] for line in status.splitlines() if line}
    return last, dirty


def build():
    last, dirty = _git_dates()
    today = datetime.date.today().isoformat()
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for url, srcs in expected_urls():
        dates = [today if (s in dirty or s not in last) else last[s] for s in srcs]
        out.append(f"  <url><loc>{escape(url)}</loc><lastmod>{max(dates)}</lastmod></url>")
    out.append("</urlset>")
    return "\n".join(out) + "\n"


def sitemap_urls():
    """URLs currently in sitemap.xml, or None if the file doesn't exist."""
    if not os.path.isfile(SITEMAP):
        return None
    with open(SITEMAP, encoding="utf-8") as f:
        return LOC_RE.findall(f.read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="report only, change nothing")
    args = ap.parse_args()

    new = build()
    old = None
    if os.path.isfile(SITEMAP):
        with open(SITEMAP, encoding="utf-8", newline="") as f:
            old = f.read().replace("\r\n", "\n")
    count = new.count("<url>")
    if old == new:
        print(f"sitemap.xml up to date ({count} URLs).")
        return
    if args.check:
        print(f"sitemap.xml would change ({count} URLs).")
        return
    with open(SITEMAP, "w", encoding="utf-8", newline="\n") as f:
        f.write(new)
    print(f"Wrote sitemap.xml ({count} URLs).")


if __name__ == "__main__":
    main()
