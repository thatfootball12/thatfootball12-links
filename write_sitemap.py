#!/usr/bin/env python3
"""
Writes the sitemap at the repo root: sitemap.xml is a sitemap index that
points to four child sitemaps, one per section:

    sitemap-pages.xml     homepage, shop grid, generator, gift guide,
                          privacy, Work with me
    sitemap-outfits.xml   outfits/ and videos/ hubs, category and
                          campaign pages
    sitemap-products.xml  product detail pages (from products.json)
    sitemap-blog.xml      blog listing and published posts

The submitted URL (sitemap.xml) stays the same. Each child's <lastmod> in
the index is the newest <lastmod> inside it. A section with no URLs is
left out of the index and its file removed (an empty <urlset> is an
error in Search Console).

Usage:
    python write_sitemap.py            (write the sitemap files that changed)
    python write_sitemap.py --check    (report only, change nothing)

Included:
  - The homepage, the shop grid (products/), the outfit generator, the
    gift guide (gift-guide/), the privacy page and Work with me
  - The blog listing (blog/) and every published post (blog/<slug>/,
    built by build_blog.py). Drafts (blog/drafts/<slug>/, noindex) never.
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
domain root to advertise the sitemap from (a robots.txt in this repo
would be served under /thatfootball12-links/, where crawlers never look
for one). Submit
https://thatfootball12.github.io/thatfootball12-links/sitemap.xml in
Google Search Console instead; the child sitemaps are found through it.

sync_catalog.py imports expected_urls() and sitemap_urls() from here to
report pages missing from the sitemap and entries whose page is gone.
sitemap_urls() returns the page URLs from every child sitemap the index
lists (or from sitemap.xml itself if it's still a plain <urlset>).
"""

import argparse
import datetime
import glob
import json
import os
import re
import subprocess
from xml.sax.saxutils import escape

import gift_guide

REPO = os.path.dirname(os.path.abspath(__file__))
PRODUCTS_JSON = os.path.join(REPO, "products.json")
SITEMAP = os.path.join(REPO, "sitemap.xml")
SITE = "https://thatfootball12.github.io/thatfootball12-links/"
# Section -> child sitemap filename, in index order.
SECTIONS = {
    "pages": "sitemap-pages.xml",
    "outfits": "sitemap-outfits.xml",
    "products": "sitemap-products.xml",
    "blog": "sitemap-blog.xml",
}
NS = 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'

REFRESH_RE = re.compile(r'http-equiv="refresh"', re.I)
NOINDEX_RE = re.compile(r'<meta name="robots" content="[^"]*noindex', re.I)
LOC_RE = re.compile(r"<loc>([^<]+)</loc>")


def _abs(rel):
    return os.path.join(REPO, rel.replace("/", os.sep))


def _rel_glob(pattern):
    return sorted(os.path.relpath(p, REPO).replace(os.sep, "/")
                  for p in glob.glob(os.path.join(REPO, pattern)))


def is_redirect(rel):
    with open(_abs(rel), encoding="utf-8", errors="replace") as f:
        return bool(REFRESH_RE.search(f.read()))


def is_noindex(rel):
    with open(_abs(rel), encoding="utf-8", errors="replace") as f:
        return bool(NOINDEX_RE.search(f.read()))


def url_for(rel):
    return SITE + re.sub(r"index\.html$", "", rel)


def page_for(url):
    """Repo-relative index.html path for a sitemap URL (None if off-site)."""
    if not url.startswith(SITE):
        return None
    return url[len(SITE):] + "index.html"


def _entries():
    """Ordered list of (section, url, [source files whose last change sets
    lastmod])."""
    entries = [
        ("pages", "index.html", ["index.html"]),
        ("pages", "products/index.html", ["products/index.html", "products.json"]),
        ("pages", "generator/index.html", ["generator/index.html", "generator.json"]),
    ]
    for rel in ("gift-guide/index.html", "privacy/index.html", "work-with-me/index.html"):
        if os.path.isfile(_abs(rel)):
            entries.append(("pages", rel, [rel]))
    for rel in _rel_glob("blog/index.html") + _rel_glob("blog/*/index.html"):
        # blog/drafts/<slug>/ is two levels down, so the glob never sees a
        # draft; the noindex check is a second guard.
        if not is_redirect(rel) and not is_noindex(rel):
            entries.append(("blog", rel, [rel]))
    for rel in ["outfits/index.html", "videos/index.html"] + \
            _rel_glob("outfits/*/index.html") + _rel_glob("videos/*/index.html"):
        entries.append(("outfits", rel, [rel]))
    for rel in _rel_glob("outfits/*/*/index.html") + _rel_glob("videos/*/*/index.html"):
        if not is_redirect(rel):
            entries.append(("outfits", rel, [rel]))
    with open(PRODUCTS_JSON, encoding="utf-8") as f:
        products = json.load(f)
    for rel in sorted(p["detail_page_url"] for p in products if not gift_guide.listing_only(p)):
        if os.path.isfile(_abs(rel)) and not is_redirect(rel):
            entries.append(("products", rel, [rel]))
    return [(section, url_for(rel), srcs) for section, rel, srcs in entries]


def expected_urls():
    """Ordered list of (url, [source files whose last change sets lastmod])."""
    return [(url, srcs) for _, url, srcs in _entries()]


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
    """{filename: content} for sitemap.xml (the index) and each non-empty
    child sitemap."""
    last, dirty = _git_dates()
    today = datetime.date.today().isoformat()
    rows = {section: [] for section in SECTIONS}
    for section, url, srcs in _entries():
        dates = [today if (s in dirty or s not in last) else last[s] for s in srcs]
        rows[section].append((url, max(dates)))
    files = {}
    index = ['<?xml version="1.0" encoding="UTF-8"?>', f"<sitemapindex {NS}>"]
    for section, name in SECTIONS.items():
        if not rows[section]:
            continue
        out = ['<?xml version="1.0" encoding="UTF-8"?>', f"<urlset {NS}>"]
        for url, lastmod in rows[section]:
            out.append(f"  <url><loc>{escape(url)}</loc><lastmod>{lastmod}</lastmod></url>")
        out.append("</urlset>")
        files[name] = "\n".join(out) + "\n"
        newest = max(lastmod for _, lastmod in rows[section])
        index.append(f"  <sitemap><loc>{escape(SITE + name)}</loc><lastmod>{newest}</lastmod></sitemap>")
    index.append("</sitemapindex>")
    files["sitemap.xml"] = "\n".join(index) + "\n"
    return files


def _read(name):
    path = os.path.join(REPO, name)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8", newline="") as f:
        return f.read().replace("\r\n", "\n")


def sitemap_urls():
    """Page URLs currently in the sitemap (every child the index lists, or
    sitemap.xml itself if it's a plain <urlset>), or None if sitemap.xml
    doesn't exist. A missing child file contributes nothing, so its pages
    get reported as missing."""
    top = _read("sitemap.xml")
    if top is None:
        return None
    if "<sitemapindex" not in top:
        return LOC_RE.findall(top)
    urls = []
    for loc in LOC_RE.findall(top):
        if loc.startswith(SITE):
            child = _read(loc[len(SITE):])
            if child is not None:
                urls.extend(LOC_RE.findall(child))
    return urls


def _stray_children(files):
    """Section sitemap files on disk that the new index doesn't list."""
    return [n for n in SECTIONS.values() if n not in files and _read(n) is not None]


def is_stale():
    """True if regenerating would change any sitemap file (e.g. a <lastmod>)."""
    files = build()
    return any(_read(n) != c for n, c in files.items()) or bool(_stray_children(files))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="report only, change nothing")
    args = ap.parse_args()

    files = build()
    changed = [n for n, c in files.items() if _read(n) != c]
    stray = _stray_children(files)
    summary = ", ".join(f"{n} {c.count('<url>')}" for n, c in files.items() if n != "sitemap.xml")
    total = sum(c.count("<url>") for c in files.values())
    if not changed and not stray:
        print(f"Sitemap up to date ({total} URLs: {summary}).")
        return
    if args.check:
        print(f"Sitemap would change: {', '.join(changed + stray)} ({total} URLs: {summary}).")
        return
    for name in changed:
        with open(os.path.join(REPO, name), "w", encoding="utf-8", newline="\n") as f:
            f.write(files[name])
    for name in stray:
        os.remove(os.path.join(REPO, name))
    print(f"Wrote {', '.join(changed)}"
          + (f"; removed {', '.join(stray)}" if stray else "")
          + f" ({total} URLs: {summary}).")


if __name__ == "__main__":
    main()
