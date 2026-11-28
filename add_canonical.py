#!/usr/bin/env python3
"""
Writes a self-referencing canonical link and a matching og:url into
every content page's <head>, between <!-- canonical:start/end -->
markers. Safe to re-run: the block is replaced in place.

Usage:
    python add_canonical.py            (write/refresh blocks)
    python add_canonical.py --check    (report only, change nothing)

Both tags carry the page's own absolute URL with its trailing slash and
no query string, the same URL write_sitemap.py lists:

    https://thatfootball12.github.io/thatfootball12-links/<path>/

Pins link with UTM parameters (make_pinterest_csv.py), so without a
canonical Google can treat every ?utm_... variant as its own page.

Pages written (WRITE_SCOPE): the homepage, products/, generator/,
gift-guide/, privacy/, and every page under outfits/ and videos/ (hubs,
category pages, campaign pages, product detail pages). A new page copied
from an existing one carries the old page's block, and the next run
points it at the new page's own URL. The script also removes any
canonical or og:url tag outside the block, so a copied og:url can't
survive next to the right one (which is how
outfits/night-out/night-out-nov-23/ ended up pointing at nov-2). On a
page with no block yet, the block goes where its og:url was, else right
before </head>.

Left alone:
  - Redirect pages (meta refresh): the root redirect stubs (see
    CLAUDE.md) and retired campaign pages. They already carry a
    canonical pointing at the page they redirect to.
  - blog/: build_blog.py writes its own canonical and og:url.
  - work-with-me/: its canonical is hand-written.
  - archive/ (a list of links to the redirect stubs, not in the
    sitemap) and the Search Console verification file.

sync_catalog.py imports audit() from here (report item 17). It fails on
any page in WRITE_SCOPE whose block is missing or stale, any other
non-redirect page (blog, work-with-me) whose canonical is missing or
isn't its own URL, any page whose og:url isn't its own URL, any page
with more than one canonical, and any sitemap <loc> that doesn't equal
its page's canonical.
"""

import argparse
import re

from add_analytics import _abs, _nl, all_html, read_page, write_page
from write_sitemap import page_for, sitemap_urls, url_for

START = "<!-- canonical:start -->"
END = "<!-- canonical:end -->"
BLOCK_RE = re.compile(r"[ \t]*" + re.escape(START) + r".*?" + re.escape(END) + r"[ \t]*\r?\n?", re.DOTALL)
HEAD_END_RE = re.compile(r"</head>", re.I)
REFRESH_RE = re.compile(r'http-equiv="refresh"', re.I)
NOINDEX_RE = re.compile(r'<meta name="robots" content="[^"]*noindex', re.I)
CANON_TAG_RE = re.compile(r'[ \t]*<link\b[^>]*\brel="canonical"[^>]*>[ \t]*\r?\n?', re.I)
OG_URL_TAG_RE = re.compile(r'[ \t]*<meta\b[^>]*\bproperty="og:url"[^>]*>[ \t]*\r?\n?', re.I)
HREF_RE = re.compile(r'\bhref="([^"]*)"', re.I)
CONTENT_RE = re.compile(r'\bcontent="([^"]*)"', re.I)

# Pages this script writes the block into: exact paths, plus prefixes.
WRITE_PAGES = {"index.html", "products/index.html", "generator/index.html",
               "gift-guide/index.html", "privacy/index.html"}
WRITE_PREFIXES = ("outfits/", "videos/")
# Never checked: not content pages.
SKIP = {"googlec6449ad50316914e.html", "archive/index.html"}

TAGS = """<!-- canonical:start -->
<link rel="canonical" href="__U__">
<meta property="og:url" content="__U__">
<!-- canonical:end -->"""


def is_redirect(page_html):
    return bool(REFRESH_RE.search(page_html))


def in_write_scope(rel):
    return rel in WRITE_PAGES or rel.startswith(WRITE_PREFIXES)


def pages():
    """[(rel, html)] for every non-redirect page this script checks."""
    out = []
    for rel in all_html():
        if rel in SKIP:
            continue
        page = read_page(_abs(rel))
        if not is_redirect(page):
            out.append((rel, page))
    return out


def targets():
    return [rel for rel, _ in pages() if in_write_scope(rel)]


def expected_block(rel, page_html):
    return _nl(page_html, TAGS.replace("__U__", url_for(rel)))


def current_block(page_html):
    m = BLOCK_RE.search(page_html)
    return m.group(0).strip(" \t") if m else None


def _outside_block(page_html):
    return BLOCK_RE.sub("", page_html)


def canonicals(page_html):
    return [m.group(1) for t in CANON_TAG_RE.finditer(page_html)
            for m in [HREF_RE.search(t.group(0))] if m]


def og_urls(page_html):
    return [m.group(1) for t in OG_URL_TAG_RE.finditer(page_html)
            for m in [CONTENT_RE.search(t.group(0))] if m]


def apply(page_html, block):
    """Put block in the page, removing any canonical/og:url outside it."""
    m = BLOCK_RE.search(page_html)
    if m:
        page_html = page_html[:m.start()] + "\x00" + page_html[m.end():]
    else:
        og = OG_URL_TAG_RE.search(page_html)
        if og:
            page_html = page_html[:og.start()] + "\x00" + page_html[og.end():]
    page_html = CANON_TAG_RE.sub("", OG_URL_TAG_RE.sub("", page_html))
    if "\x00" not in page_html:
        h = HEAD_END_RE.search(page_html)
        if not h:
            raise ValueError("no </head>")
        return page_html[:h.start()] + block + page_html[h.start():]
    return page_html.replace("\x00", block)


def status(rel, page_html):
    """'ok', or why the page needs the script run."""
    if not HEAD_END_RE.search(page_html):
        return "no </head> for"
    have = current_block(page_html)
    if have is None:
        return "missing"
    if have.replace("\r\n", "\n") != expected_block(rel, page_html).replace("\r\n", "\n"):
        return "stale"
    outside = _outside_block(page_html)
    if canonicals(outside) or og_urls(outside):
        return "duplicate canonical/og:url outside"
    return "ok"


def audit():
    """[(page, what)] for every page whose canonical or og:url is wrong."""
    issues = []
    canon_of = {}
    for rel, page in pages():
        want = url_for(rel)
        canon = canonicals(page)
        canon_of[rel] = canon
        if in_write_scope(rel):
            st = status(rel, page)
            if st != "ok":
                issues.append((rel, f"{st} canonical block"))
            continue
        # blog/ and work-with-me/ write their own tags.
        if not canon:
            if not NOINDEX_RE.search(page):  # blog drafts are noindex
                issues.append((rel, "no canonical"))
        elif len(canon) > 1:
            issues.append((rel, f"{len(canon)} canonical tags"))
        elif canon[0] != want:
            issues.append((rel, f"canonical is {canon[0]}"))
        for og in og_urls(page):
            if og != want:
                issues.append((rel, f"og:url is {og}"))
    for url in sitemap_urls() or []:
        rel = page_for(url)
        if rel is None:
            issues.append((url, "sitemap <loc> is off-site"))
        elif not canon_of.get(rel):
            continue  # gone/redirect pages are item 5's job, no canonical is reported above
        elif canon_of[rel] != [url]:
            issues.append((url, f"sitemap <loc> doesn't equal the page's canonical {canon_of[rel]}"))
    return issues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="report only, change nothing")
    args = ap.parse_args()

    scope = targets()
    issues = audit()
    print(f"Pages written by this script: {len(scope)}")
    print(f"Issues: {len(issues)}")
    counts = {}
    for _, what in issues:
        key = what if what.endswith("canonical block") else what.split(" is ")[0]
        counts[key] = counts.get(key, 0) + 1
    if counts:
        print("  " + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())))
    for rel, what in issues:
        if not what.endswith("canonical block") or what.startswith("no </head>"):
            print(f"  {rel}: {what}")
    fixable = [rel for rel, what in issues
               if what.endswith("canonical block") and not what.startswith("no </head>")]
    if args.check or not fixable:
        return
    for rel in fixable:
        page = read_page(_abs(rel))
        write_page(_abs(rel), apply(page, expected_block(rel, page)))
    print(f"Updated {len(fixable)} page(s).")


if __name__ == "__main__":
    main()
