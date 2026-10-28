#!/usr/bin/env python3
"""
Writes the self-hosted web font block (Anton, Oswald, Poppins) into
every site page's <head>, between <!-- fonts:start/end --> markers, and
removes the Google Fonts <link> / preconnect tags it replaces. Safe to
re-run: the block is replaced in place.

Usage:
    python add_fonts.py            (write/refresh blocks)
    python add_fonts.py --check    (report only, change nothing; exit 1 if
                                    any page needs changes or a font file
                                    is missing)

sync_catalog.py imports audit() and missing_fonts() from here (report
item 14, which fails CI): any page whose block is missing or stale, any
non-stub page that still references googleapis.com or gstatic.com, and
any font file missing from assets/fonts/web/.

Why self-hosted: loading the fonts from Google sent every visitor's IP
address to Google before any cookie choice. Nothing in the block
contacts another site.

Pages: every .html file except redirect pages (meta refresh: the root
redirect stubs, which CLAUDE.md says not to touch, and retired campaign
pages) and the Search Console verification file. None of those load
fonts.

The files are Google Fonts' own latin-subset WOFF2 files (SIL Open Font
License; the licences are in assets/fonts/), the same bytes Chrome got
from fonts.gstatic.com. The audit for this change found no visible text
outside the latin subset except arrows, emoji and symbols, which none of
Google's subsets for these families cover either, so they fall back to
system fonts exactly as before. Oswald is one variable file. The
@font-face rules reproduce what each page used to request from Google:
  - most pages asked for Oswald 500;600 only, so Oswald is declared as
    500 600 (a request for 400 renders at 500 and for 700 at 600, as it
    did when Google served only those two weights);
  - the pages that asked for Oswald 400;500;600;700 (the homepage, shop
    grid, hubs, category pages, gift guide, generator, privacy page and
    some campaign pages) get 400 700.
The block itself records which one a page has, so a new page copied
from an existing one keeps its look. Anton is 400 only (headings that
ask for bold get the browser's synthetic bold, as before) and Poppins is
400, 500 and 600 (bold text uses 600, as before).

Only Anton 400 and Poppins 400, the fonts on screen as a page loads, are
preloaded. crossorigin is required on a font preload even for a
same-site file, or the browser fetches it twice.

Paths are relative, like add_favicons.py's icons: this is a GitHub
Pages project site served under /thatfootball12-links/, where a
root-relative /assets/ would point at the wrong site. url() in an inline
<style> resolves against the page, so each page gets its own depth.
"""

import argparse
import os
import re
import sys

from add_analytics import REFRESH_RE, _abs, _nl, all_html, read_page, write_page

FONT_DIR = "assets/fonts/web/"
EXCLUDE = {"googlec6449ad50316914e.html"}

# (family, weight descriptor, file)
FACES = [
    ("Anton", "400", "anton-400-latin.woff2"),
    ("Oswald", "__OSWALD__", "oswald-latin.woff2"),
    ("Poppins", "400", "poppins-400-latin.woff2"),
    ("Poppins", "500", "poppins-500-latin.woff2"),
    ("Poppins", "600", "poppins-600-latin.woff2"),
]
PRELOAD = ["anton-400-latin.woff2", "poppins-400-latin.woff2"]
OSWALD = {"narrow": "500 600", "full": "400 700"}

START = "<!-- fonts:start -->"
END = "<!-- fonts:end -->"
BLOCK_RE = re.compile(r"[ \t]*" + re.escape(START) + r".*?" + re.escape(END) + r"[ \t]*\r?\n?", re.DOTALL)
GOOGLE_RE = re.compile(r"googleapis\.com|gstatic\.com", re.I)
GOOGLE_TAG_RE = re.compile(r"[ \t]*<link\b[^>]*fonts\.(?:googleapis|gstatic)\.com[^>]*>[ \t]*\r?\n?", re.I)
GOOGLE_FULL_RE = re.compile(r"fonts\.googleapis\.com/css2\?[^\"']*Oswald:wght@400;500;600;700", re.I)
OSWALD_FULL_RE = re.compile(r"font-family:'Oswald';[^}]*font-weight:" + re.escape(OSWALD["full"]))
HEAD_END_RE = re.compile(r"</head>", re.I)


def targets():
    out = []
    for rel in all_html():
        if rel in EXCLUDE:
            continue
        if REFRESH_RE.search(read_page(_abs(rel))):
            continue
        out.append(rel)
    return out


def font_href(rel):
    return "../" * rel.count("/") + FONT_DIR


def variant(page_html):
    """"full" or "narrow" Oswald, from the page's block or, before the
    first run, from the Google Fonts URL it replaces."""
    m = BLOCK_RE.search(page_html)
    if m:
        return "full" if OSWALD_FULL_RE.search(m.group(0)) else "narrow"
    return "full" if GOOGLE_FULL_RE.search(page_html) else "narrow"


def expected_block(rel, page_html):
    p = font_href(rel)
    lines = [START]
    lines += [f'<link rel="preload" href="{p}{f}" as="font" type="font/woff2" crossorigin>' for f in PRELOAD]
    lines.append("<style>")
    for family, weight, f in FACES:
        weight = weight.replace("__OSWALD__", OSWALD[variant(page_html)])
        lines.append(f"@font-face{{font-family:'{family}';font-style:normal;font-weight:{weight};"
                     f"font-display:swap;src:url({p}{f}) format('woff2');}}")
    lines += ["</style>", END]
    return _nl(page_html, "\n".join(lines))


def current_block(page_html):
    m = BLOCK_RE.search(page_html)
    return m.group(0).strip(" \t") if m else None


def apply(rel, page_html):
    """The page with its block written and the Google Fonts tags removed.
    The block goes where the block or the first Google tag was, else
    right before </head>."""
    block = expected_block(rel, page_html)
    m = BLOCK_RE.search(page_html) or GOOGLE_TAG_RE.search(page_html)
    if m:
        at = m.start()
        page_html = page_html[:at] + "\x00" + page_html[m.end():]
    page_html = GOOGLE_TAG_RE.sub("", BLOCK_RE.sub("", page_html))
    if "\x00" in page_html:
        return page_html.replace("\x00", block)
    m = HEAD_END_RE.search(page_html)
    if not m:
        raise ValueError("no </head>")
    return page_html[:m.start()] + block + page_html[m.start():]


def status(rel, page_html):
    if not HEAD_END_RE.search(page_html):
        return "no </head> for"
    have = current_block(page_html)
    if have is None:
        return "missing"
    if have.replace("\r\n", "\n") != expected_block(rel, page_html).replace("\r\n", "\n"):
        return "stale"
    if GOOGLE_RE.search(page_html):
        return "google reference on"
    return "ok"


def missing_fonts():
    return [FONT_DIR + f for f in sorted({f for _, _, f in FACES}) if not os.path.isfile(_abs(FONT_DIR + f))]


def is_root_stub(rel, page_html):
    return rel.count("/") == 1 and bool(REFRESH_RE.search(page_html))


def audit():
    """[(page, what)] for every page whose fonts block isn't ok, and for
    any other non-stub page (a retired campaign redirect) that references
    Google's servers."""
    issues = []
    want = set(targets())
    for rel in all_html():
        if rel in EXCLUDE:
            continue
        page = read_page(_abs(rel))
        if rel in want:
            st = status(rel, page)
            if st != "ok":
                issues.append((rel, f"{st} fonts block" if st in ("missing", "stale") else f"{st} page"))
        elif not is_root_stub(rel, page) and GOOGLE_RE.search(page):
            issues.append((rel, "google reference on redirect page"))
    return issues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="report only, change nothing")
    args = ap.parse_args()

    pages = targets()
    issues = audit()
    missing = missing_fonts()
    print(f"Pages in scope: {len(pages)}")
    for path in missing:
        print(f"  ERROR: {path} is missing")
    print(f"Needing changes: {len(issues)}")
    counts = {}
    for rel, what in issues:
        counts[what] = counts.get(what, 0) + 1
    if counts:
        print("  " + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())))
    fixable = [rel for rel, what in issues if not what.startswith(("no </head>", "google reference on redirect"))]
    for rel, what in issues:
        if what.startswith("no </head>"):
            print(f"  WARNING: {rel} has no </head>; add the block by hand")
        elif what.startswith("google reference on redirect"):
            print(f"  WARNING: {rel} is a redirect page that loads from Google; remove it by hand")
    if args.check:
        sys.exit(1 if issues or missing else 0)
    for rel in fixable:
        write_page(_abs(rel), apply(rel, read_page(_abs(rel))))
    if fixable:
        print(f"Updated {len(fixable)} page(s).")
    left = audit()
    if left or missing:
        print(f"Still not ok: {len(left)} page(s)")
        for rel, what in left[:20]:
            print(f"  {rel}: {what}")
        sys.exit(1)


if __name__ == "__main__":
    main()
