#!/usr/bin/env python3
"""
Writes the ThatFootball12 favicon / apple-touch-icon <link> tags into
every site page's <head>, right before </head>, between
<!-- favicons:start/end --> markers. Safe to re-run: the block is
replaced in place.

Usage:
    python add_favicons.py            (write/refresh blocks)
    python add_favicons.py --check    (report only, change nothing)

sync_catalog.py imports audit() from here and reports any page whose
block is missing or stale (report item 9), and any icon file that's
missing from assets/icons/.

Pages: every .html file in the repo, including archive/ and the root
redirect stubs (see CLAUDE.md: this block is the one sanctioned edit to
them, so a browser tab or bookmark shows the icon during the redirect
too). The only exclusion is the Search Console verification file, which
isn't a page and has to keep its exact contents.

Icons live in assets/icons/ (favicon.ico holds 16, 32 and 48). The hrefs
are relative, like add_analytics.py's privacy link: this is a GitHub
Pages project site served under /thatfootball12-links/, where a
root-relative /assets/ would point at the wrong site. Browsers that
ignore the tags and ask for /favicon.ico at the domain root get
thatfootball12.github.io's root, which this repo doesn't serve.
icon-512.png isn't linked from pages; it's there for a web app manifest
if the site ever gets one.
"""

import argparse
import os
import re

from add_analytics import REPO, _abs, _nl, all_html, read_page, write_page

ICON_DIR = "assets/icons/"
ICONS = ["favicon.ico", "favicon-32x32.png", "icon-192.png", "apple-touch-icon.png", "icon-512.png"]
EXCLUDE = {"googlec6449ad50316914e.html"}

START = "<!-- favicons:start -->"
END = "<!-- favicons:end -->"
BLOCK_RE = re.compile(r"[ \t]*" + re.escape(START) + r".*?" + re.escape(END) + r"[ \t]*\r?\n?", re.DOTALL)
HEAD_END_RE = re.compile(r"</head>", re.I)

TAGS = """<!-- favicons:start -->
<link rel="icon" href="__P__favicon.ico" sizes="any">
<link rel="icon" type="image/png" sizes="32x32" href="__P__favicon-32x32.png">
<link rel="icon" type="image/png" sizes="192x192" href="__P__icon-192.png">
<link rel="apple-touch-icon" sizes="180x180" href="__P__apple-touch-icon.png">
<!-- favicons:end -->"""


def targets():
    return [rel for rel in all_html() if rel not in EXCLUDE]


def icon_href(rel):
    return "../" * rel.count("/") + ICON_DIR


def expected_block(rel, page_html):
    return _nl(page_html, TAGS.replace("__P__", icon_href(rel)))


def current_block(page_html):
    m = BLOCK_RE.search(page_html)
    return m.group(0).strip(" \t") if m else None


def apply(page_html, block):
    stripped = BLOCK_RE.sub("", page_html)
    m = HEAD_END_RE.search(stripped)
    if not m:
        raise ValueError("no </head>")
    return stripped[:m.start()] + block + stripped[m.start():]


def status(rel, page_html):
    if not HEAD_END_RE.search(page_html):
        return "no </head> for"
    have = current_block(page_html)
    if have is None:
        return "missing"
    want = expected_block(rel, page_html)
    return "ok" if have.replace("\r\n", "\n") == want.replace("\r\n", "\n") else "stale"


def missing_icons():
    return [ICON_DIR + name for name in ICONS if not os.path.isfile(_abs(ICON_DIR + name))]


def audit():
    """[(page, what)] for every page whose favicon block isn't ok."""
    issues = []
    for rel in targets():
        st = status(rel, read_page(_abs(rel)))
        if st != "ok":
            issues.append((rel, f"{st} favicon block"))
    return issues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="report only, change nothing")
    args = ap.parse_args()

    pages = targets()
    issues = audit()
    print(f"Pages in scope: {len(pages)}")
    for path in missing_icons():
        print(f"  WARNING: {path} is missing")
    print(f"Needing changes: {len(issues)}")
    counts = {}
    for rel, what in issues:
        counts[what] = counts.get(what, 0) + 1
    if counts:
        print("  " + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())))
    fixable = [rel for rel, what in issues if not what.startswith("no </head>")]
    for rel, what in issues:
        if what.startswith("no </head>"):
            print(f"  WARNING: {rel} has no </head>; add the block by hand")
    if args.check or not fixable:
        return
    for rel in fixable:
        page = read_page(_abs(rel))
        write_page(_abs(rel), apply(page, expected_block(rel, page)))
    print(f"Updated {len(fixable)} page(s).")


if __name__ == "__main__":
    main()
