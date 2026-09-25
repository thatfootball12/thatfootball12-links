#!/usr/bin/env python3
"""
Writes the Google Analytics 4 tag (and, where there are affiliate links,
affiliate_click tracking) into every site page's <head>. Safe to re-run:
the block lives between marker comments and is replaced in place.

Usage:
    python add_analytics.py            (write/refresh blocks)
    python add_analytics.py --check    (report only, change nothing)

sync_catalog.py imports status() from here and reports any page whose
block is missing, stale, or present where it shouldn't be.

Pages (485): homepage, shop grid, the outfits/ and videos/ hubs, every
category page, every campaign page (legacy link-list pages and redirect
pages like the retired this-or-that-aug-14 included), and every product
detail page. Not touched: archive/, the root redirect-stub folders
(see CLAUDE.md), and the Search Console verification file.

The block goes right after <meta charset>, not immediately after <head>:
browsers only look for the charset in the first 1024 bytes, and a
detail page's block alone is longer than that.

affiliate_click tracking:
  - Product detail pages: the .shop link. Parameters come from the
    page's products.json record. value/currency are sent for SHEIN only;
    Amazon prices in products.json are stale and deliberately not shown
    on the pages, and the Awin record has no price.
  - Legacy link-list campaign pages: every .link-card link. There's no
    products.json record, so retailer comes from the link's domain,
    product_name from its visible text, and product_id is
    "<theme>/<campaign>/<slugified name>". No value/currency.
  - Homepage: .link-card and .affiliate-banner links, same as legacy
    (product_id "home/<slug>"). Social profile links (TikTok, Instagram,
    Pinterest) aren't affiliate links and are skipped.

Every tracked link opens in a new tab (target="_blank"), so the page
isn't unloading when the event is sent. The handler therefore never
calls preventDefault or delays navigation: it sends the event and lets
the browser open the link natively. Cancelling the click and navigating
from a callback/setTimeout (the old analytics.js outbound-link pattern)
would get new tabs caught by popup blockers and ties the link to GA
loading. The call is wrapped in try/catch so a tracking error can never
stop the link. gtag() is defined inline by the snippet itself, so it
exists even when an ad blocker stops gtag.js from loading (the events
just go nowhere). Middle-clicks are caught via auxclick; "open in new
tab" from the context menu can't be tracked by any method.
"""

import argparse
import glob
import json
import os
import re

REPO = os.path.dirname(os.path.abspath(__file__))
PRODUCTS_JSON = os.path.join(REPO, "products.json")
MEASUREMENT_ID = "G-E3HV1TFPEN"

START = "<!-- analytics:start -->"
END = "<!-- analytics:end -->"
BLOCK_RE = re.compile(r"[ \t]*" + re.escape(START) + r".*?" + re.escape(END) + r"[ \t]*\r?\n?", re.DOTALL)
CHARSET_RE = re.compile(r'<meta charset="[^"]*">[ \t]*\r?\n')

GTAG = """<!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id=G-E3HV1TFPEN"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('js', new Date());
  gtag('config', 'G-E3HV1TFPEN');
</script>"""

TRACKER = """<script>
(function () {
  var P = %(product)s, C = %(context)s, SEL = %(selector)s;
  var SKIP = /(^|\\.)(tiktok\\.com|instagram\\.com|pin\\.it|pinterest\\.[a-z.]+)$/;
  function retailer(host) {
    if (/(^|\\.)amazon\\.|(^|\\.)amzn\\.to$/.test(host)) return 'Amazon';
    if (/(^|\\.)shein\\.com$/.test(host)) return 'SHEIN';
    if (/(^|\\.)awin1\\.com$|(^|\\.)tidd\\.ly$/.test(host)) return 'Awin';
    if (/(^|\\.)tee\\.pub$|(^|\\.)teepublic\\.com$/.test(host)) return 'TeePublic';
    if (/(^|\\.)redbubble\\.com$/.test(host)) return 'Redbubble';
    return host;
  }
  function linkParams(a) {
    var host = a.hostname.replace(/^www\\./, '');
    if (SKIP.test(host)) return null;
    var t = a.querySelector('.link-text'), img = a.querySelector('img[alt]');
    var name = (t ? t.textContent : img ? img.alt : a.textContent).replace(/\\s+/g, ' ').trim();
    var slug = name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    return { retailer: retailer(host), product_id: C + '/' + slug, product_name: name };
  }
  function track(e) {
    if (e.type === 'auxclick' && e.button !== 1) return;
    var a = e.target && e.target.closest ? e.target.closest(SEL) : null;
    if (!a || !/^https?:$/.test(a.protocol)) return;
    var params = P || linkParams(a);
    if (!params) return;
    try { gtag('event', 'affiliate_click', params); } catch (err) {}
  }
  document.addEventListener('click', track);
  document.addEventListener('auxclick', track);
})();
</script>"""


def _abs(rel):
    return os.path.join(REPO, rel.replace("/", os.sep))


def _rel_glob(pattern):
    return sorted(os.path.relpath(p, REPO).replace(os.sep, "/")
                  for p in glob.glob(os.path.join(REPO, pattern)))


def _js(value):
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def load_products():
    with open(PRODUCTS_JSON, encoding="utf-8") as f:
        return json.load(f)


def read_page(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def write_page(path, text):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def detail_params(p):
    params = {"retailer": p["retailer"], "product_id": p["id"], "product_name": p["name"]}
    if p["retailer"] == "SHEIN" and p["price"] is not None and p["currency"]:
        params["value"] = p["price"]
        params["currency"] = p["currency"]
    return params


def targets():
    """{repo-relative page: tracking config or None (gtag only)}.
    A tracking config is (product params or None, context, selector)."""
    out = {rel: None for rel in
           ["index.html", "products/index.html", "outfits/index.html", "videos/index.html"]
           + _rel_glob("outfits/*/index.html") + _rel_glob("videos/*/index.html")}
    out["index.html"] = (None, "home", "a.link-card, a.affiliate-banner")
    for rel in _rel_glob("outfits/*/*/index.html") + _rel_glob("videos/*/*/index.html"):
        campaign_dir = os.path.dirname(_abs(rel))
        if glob.glob(os.path.join(campaign_dir, "*", "index.html")):
            out[rel] = None
        else:  # legacy link-list page (or a retired redirect page)
            context = "/".join(rel.split("/")[1:3])
            out[rel] = (None, context, "a.link-card")
    for p in load_products():
        rel = p["detail_page_url"]
        if os.path.isfile(_abs(rel)):
            out[rel] = (detail_params(p), None, "a.shop")
    return out


def expected_block(config, page_html):
    parts = [START, GTAG]
    if config is not None:
        product, context, selector = config
        parts.append(TRACKER % {"product": _js(product), "context": _js(context), "selector": _js(selector)})
    parts.append(END)
    nl = "\r\n" if "\r\n" in page_html else "\n"
    return nl.join("\n".join(parts).split("\n")) + nl


def current_block(page_html):
    m = BLOCK_RE.search(page_html)
    return m.group(0).strip(" \t") if m else None


def apply(page_html, block):
    stripped = BLOCK_RE.sub("", page_html)
    if block is None:
        return stripped
    m = CHARSET_RE.search(stripped)
    if not m:
        raise ValueError("no <meta charset> line")
    return stripped[:m.end()] + block + stripped[m.end():]


def status(config, page_html, wanted=True):
    """'ok', 'missing', 'stale', or 'unwanted'. Line endings are ignored:
    git's autocrlf rewrites them on checkout, which isn't a content change."""
    have = current_block(page_html)
    if not wanted:
        return "unwanted" if have is not None else "ok"
    if have is None:
        return "missing"
    want = expected_block(config, page_html)
    return "ok" if have.replace("\r\n", "\n") == want.replace("\r\n", "\n") else "stale"


def all_html():
    out = []
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
        out += [os.path.relpath(os.path.join(root, f), REPO).replace(os.sep, "/")
                for f in files if f.endswith(".html")]
    return sorted(out)


def audit():
    """[(page, status)] for every .html file in the repo whose status isn't ok."""
    want = targets()
    issues = []
    for rel in all_html():
        page = read_page(_abs(rel))
        st = status(want.get(rel), page, wanted=rel in want)
        if st != "ok":
            issues.append((rel, st))
    return issues


def untracked_links():
    """Product detail pages with no outbound a.shop link for the handler to catch."""
    bad = []
    for rel, config in targets().items():
        if config is not None and config[2] == "a.shop":
            if not re.search(r'<a class="shop" href="https?://', read_page(_abs(rel))):
                bad.append(rel)
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="report only, change nothing")
    args = ap.parse_args()

    want = targets()
    issues = audit()
    tracked = sum(1 for c in want.values() if c is not None)
    print(f"Pages in scope: {len(want)} ({tracked} with affiliate_click tracking)")
    print(f"Needing changes: {len(issues)}")
    counts = {}
    for rel, st in issues:
        counts[st] = counts.get(st, 0) + 1
    if counts:
        print("  " + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())))
    for rel in untracked_links():
        print(f"  WARNING: no outbound a.shop link to track on {rel}")
    if args.check or not issues:
        return
    for rel, st in issues:
        page = read_page(_abs(rel))
        block = expected_block(want[rel], page) if rel in want else None
        write_page(_abs(rel), apply(page, block))
    print(f"Updated {len(issues)} page(s).")


if __name__ == "__main__":
    main()
