#!/usr/bin/env python3
"""
Writes the consent-gated Google Analytics 4 tag (and, where there are
affiliate links, affiliate_click tracking) into every site page's <head>,
plus the site footer (privacy link, "Cookie settings", affiliate
disclosure) before </body>. Safe to re-run: both blocks live between
marker comments and are replaced in place.

Usage:
    python add_analytics.py            (write/refresh blocks)
    python add_analytics.py --check    (report only, change nothing)

sync_catalog.py imports audit(), untracked_links() and ungated_tags()
from here and reports any page whose blocks are missing, stale, or
present where they shouldn't be.

Pages (487): homepage, shop grid, the privacy page, the outfits/ and
videos/ hubs, every category page, every campaign page (legacy link-list
pages and redirect pages like the retired this-or-that-aug-14 included),
and every product detail page. Redirect pages (meta refresh) get the
head block but no footer: nobody sees them long enough to read it, and
the footer's layout rule would un-center their message. Not touched:
archive/, the root redirect-stub folders (see CLAUDE.md), and the Search
Console verification file.

The head block goes right after <meta charset>, not immediately after
<head>: browsers only look for the charset in the first 1024 bytes, and
a detail page's block alone is longer than that.

Consent (see privacy/index.html for the visitor-facing explanation):
  - gtag.js is not loaded at all until the visitor clicks Accept (Google
    calls this "basic" consent mode). No cookieless pings are sent before
    that, which is what Quebec's Law 25 s. 8.1 ("off by default") and
    GDPR opt-in require. Declining means it never loads, on any page,
    until the choice is changed.
  - The choice is kept in localStorage under tf12_consent as
    {v, choice, ts}. There's no backend to read a cookie, so a cookie
    would only add request weight. A choice older than 12 months, or
    saved under an older CONSENT_VERSION, counts as no choice and the
    banner asks again: bump CONSENT_VERSION when the privacy page
    changes materially. If storage is blocked the banner shows on every
    page and GA never loads.
  - Accept: clears anything the click tracker queued in dataLayer before
    consent (so pre-consent clicks are never sent), sets consent defaults
    with analytics granted and all ad signals denied, then loads gtag.js.
  - Decline (from the banner or later via "Cookie settings"): stores the
    choice, deletes the _ga / _ga_<id> cookies, and reloads the page if
    gtag.js was already running, since it can't be unloaded.
  - "Cookie settings" is a button in the footer on every page (and on
    the privacy page) that reopens the banner, showing the current
    choice. Withdrawing consent is as easy as giving it.
  - The banner is a fixed bar at the bottom, not a modal: no overlay, no
    scroll lock, and the body gets bottom padding while it's shown so it
    never covers the end of the page. Accept and Decline are identical
    buttons.

Footer: "Privacy · Cookie settings", plus the affiliate disclosure line
unless the page already carries one (the homepage and legacy pages have
their own <footer> fine-print; repeating it would stack two copies).
The privacy link is relative, since this is a GitHub Pages project site
served under /thatfootball12-links/, where a root-relative /privacy/
would point at the wrong site. Every page's body is a flex row holding
one .wrap column, so the footer's CSS (in the head block) sets
flex-wrap on body to put it on its own line under the column.

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
exists even when consent hasn't been given or an ad blocker stops
gtag.js from loading (the events just go nowhere). Middle-clicks are
caught via auxclick; "open in new tab" from the context menu can't be
tracked by any method.
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

FOOT_START = "<!-- site-footer:start -->"
FOOT_END = "<!-- site-footer:end -->"
FOOT_RE = re.compile(r"[ \t]*" + re.escape(FOOT_START) + r".*?" + re.escape(FOOT_END) + r"[ \t]*\r?\n?", re.DOTALL)
BODY_END_RE = re.compile(r"</body>", re.I)
REFRESH_RE = re.compile(r'http-equiv="refresh"', re.I)
GTM_RE = re.compile(r"googletagmanager\.com", re.I)

PRIVACY_PAGE = "privacy/index.html"
CONSENT_VERSION = 1
# Pages whose own markup already says this don't get the footer's copy.
DISCLOSURE_MARK = "earns from qualifying purchases"
DISCLOSURE = ("As an Amazon Associate, SHEIN affiliate, and Moosehill (Awin) affiliate, "
              "ThatFootball12 earns from qualifying purchases made through links on this site.")

# __PRIVACY__ and __VERSION__ are substituted per page (str.replace, not %:
# the CSS below is full of percent signs).
GTAG = """<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
</script>
<!-- Google tag (gtag.js): loaded only after the visitor accepts analytics cookies. See add_analytics.py. -->
<script>
(function () {
  var ID = 'G-E3HV1TFPEN', KEY = 'tf12_consent', VERSION = __VERSION__, MAX_AGE = 365 * 864e5;
  var PRIVACY = '__PRIVACY__', LABELS = { granted: 'Accepted', denied: 'Declined' };
  var loaded = false, bar = null;
  function stored() {
    try {
      var c = JSON.parse(localStorage.getItem(KEY));
      if (c && c.v === VERSION && Date.now() - c.ts < MAX_AGE && LABELS[c.choice]) return c.choice;
    } catch (e) {}
    return null;
  }
  function store(choice) {
    try { localStorage.setItem(KEY, JSON.stringify({ v: VERSION, choice: choice, ts: Date.now() })); } catch (e) {}
  }
  function load() {
    if (loaded) return;
    loaded = true;
    dataLayer.length = 0;
    gtag('consent', 'default', { analytics_storage: 'granted', ad_storage: 'denied', ad_user_data: 'denied', ad_personalization: 'denied' });
    gtag('js', new Date());
    gtag('config', ID);
    var s = document.createElement('script');
    s.async = true;
    s.src = 'https://www.googletagmanager.com/gtag/js?id=' + ID;
    document.head.appendChild(s);
  }
  function clearCookies() {
    var host = location.hostname;
    document.cookie.split(';').forEach(function (c) {
      var name = c.split('=')[0].trim();
      if (!/^_ga(_|$)/.test(name)) return;
      ['', host, '.' + host].forEach(function (d) {
        document.cookie = name + '=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/' + (d ? '; domain=' + d : '');
      });
    });
  }
  function showStatus() {
    var choice = stored(), els = document.querySelectorAll('[data-tf12-consent-status]');
    for (var i = 0; i < els.length; i++) els[i].textContent = LABELS[choice] || 'Not chosen yet';
    if (bar) bar.querySelector('.tf12-consent-now').hidden = !choice;
  }
  function hide() {
    if (!bar) return;
    bar.hidden = true;
    document.body.style.paddingBottom = '';
  }
  function show(focus) {
    if (!bar) {
      bar = document.createElement('div');
      bar.className = 'tf12-consent';
      bar.setAttribute('role', 'region');
      bar.setAttribute('aria-label', 'Cookie choice');
      bar.innerHTML = '<p>Can we use Google Analytics cookies to count visits and see which pages and products get checked out? Nothing is tracked unless you accept. <a href="' + PRIVACY + '">Privacy policy</a></p>' +
        '<p class="tf12-consent-now">Current choice: <b data-tf12-consent-status></b></p>' +
        '<div class="tf12-consent-btns"><button type="button" data-tf12-choice="denied">Decline</button>' +
        '<button type="button" data-tf12-choice="granted">Accept</button></div>';
      document.body.appendChild(bar);
    }
    bar.hidden = false;
    showStatus();
    pad();
    if (focus) bar.querySelector('button').focus();
  }
  function pad() {
    if (bar && !bar.hidden) document.body.style.paddingBottom = (bar.offsetHeight + 24) + 'px';
  }
  window.addEventListener('resize', pad);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(pad);
  function choose(choice) {
    store(choice);
    hide();
    showStatus();
    if (choice === 'granted') return load();
    if (loaded) gtag('consent', 'update', { analytics_storage: 'denied' });
    clearCookies();
    if (loaded) location.reload();
  }
  document.addEventListener('click', function (e) {
    var t = e.target && e.target.closest ? e.target.closest('[data-tf12-choice], [data-tf12-consent-open]') : null;
    if (!t) return;
    if (t.hasAttribute('data-tf12-consent-open')) show(true);
    else choose(t.getAttribute('data-tf12-choice'));
  });
  var initial = stored();
  if (initial === 'granted') load();
  function ready() {
    showStatus();
    if (!initial) show(false);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ready);
  else ready();
})();
</script>"""

CONSENT_CSS = """  .tf12-consent{position:fixed;left:12px;right:12px;bottom:12px;z-index:2147483000;max-width:560px;margin:0 auto;padding:14px 16px;background:#18140F;color:#F3EFE6;border:1px solid #2A2620;border-radius:12px;box-shadow:0 8px 28px rgba(0,0,0,.55);font:13px/1.5 'Poppins',system-ui,sans-serif;text-align:left;}
  .tf12-consent[hidden],.tf12-consent [hidden]{display:none;}
  .tf12-consent p{margin:0 0 12px;font-size:13px;line-height:1.5;color:#F3EFE6;}
  .tf12-consent a{color:#D4A017;}
  .tf12-consent .tf12-consent-now{color:#B8B2A4;}
  .tf12-consent-btns{display:flex;gap:10px;}
  .tf12-consent-btns button{flex:1 1 0;min-height:44px;padding:10px 12px;border:1px solid #F3EFE6;border-radius:8px;background:transparent;color:#F3EFE6;font:600 14px/1 'Oswald',system-ui,sans-serif;letter-spacing:1px;text-transform:uppercase;cursor:pointer;}
  .tf12-consent-btns button:hover,.tf12-consent-btns button:focus-visible{background:#F3EFE6;color:#0D0D0D;}"""

FOOT_CSS = """  body{flex-wrap:wrap;align-content:flex-start;}
  .tf12-foot{flex:0 0 100%;margin-top:32px;text-align:center;font:11px/1.6 'Poppins',system-ui,sans-serif;color:#B8B2A4;}
  .tf12-foot p{max-width:520px;margin:0 auto 4px;font-size:11px;line-height:1.6;color:#B8B2A4;}
  .tf12-foot .tf12-foot-links{font-size:13px;}
  .tf12-foot a,.tf12-foot button{display:inline-block;padding:6px 4px;color:#B8B2A4;text-decoration:underline;text-underline-offset:2px;}
  .tf12-foot button{background:none;border:0;font:inherit;cursor:pointer;}
  .tf12-foot a:hover,.tf12-foot button:hover{color:#D4A017;}"""

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
    if os.path.isfile(_abs(PRIVACY_PAGE)):
        out[PRIVACY_PAGE] = None
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


def privacy_href(rel):
    """Relative link from page rel to the privacy page."""
    return "../" * rel.count("/") + "privacy/"


def wants_footer(page_html):
    return not REFRESH_RE.search(page_html)


def _nl(page_html, text):
    nl = "\r\n" if "\r\n" in page_html else "\n"
    return nl.join(text.split("\n")) + nl


def expected_block(rel, config, page_html):
    css = CONSENT_CSS + ("\n" + FOOT_CSS if wants_footer(page_html) else "")
    gtag = (GTAG.replace("__PRIVACY__", privacy_href(rel))
            .replace("__VERSION__", str(CONSENT_VERSION)))
    parts = [START, gtag, "<style>\n" + css + "\n</style>"]
    if config is not None:
        product, context, selector = config
        parts.append(TRACKER % {"product": _js(product), "context": _js(context), "selector": _js(selector)})
    parts.append(END)
    return _nl(page_html, "\n".join(parts))


def expected_footer(rel, page_html):
    own = FOOT_RE.sub("", BLOCK_RE.sub("", page_html))
    lines = [FOOT_START, '<div class="tf12-foot">']
    if DISCLOSURE_MARK not in own:
        lines.append("  <p>" + DISCLOSURE + "</p>")
    lines += ['  <p class="tf12-foot-links"><a href="' + privacy_href(rel) + '">Privacy</a> · '
              '<button type="button" data-tf12-consent-open>Cookie settings</button></p>',
              "</div>", FOOT_END]
    return _nl(page_html, "\n".join(lines))


def current_block(page_html, regex=BLOCK_RE):
    m = regex.search(page_html)
    return m.group(0).strip(" \t") if m else None


def apply(page_html, block):
    stripped = BLOCK_RE.sub("", page_html)
    if block is None:
        return stripped
    m = CHARSET_RE.search(stripped)
    if not m:
        raise ValueError("no <meta charset> line")
    return stripped[:m.end()] + block + stripped[m.end():]


def apply_footer(page_html, block):
    stripped = FOOT_RE.sub("", page_html)
    if block is None:
        return stripped
    ends = list(BODY_END_RE.finditer(stripped))
    if not ends:
        raise ValueError("no </body>")
    i = ends[-1].start()
    return stripped[:i] + block + stripped[i:]


def _compare(have, want):
    if want is None:
        return "unwanted" if have is not None else "ok"
    if have is None:
        return "missing"
    # Line endings are ignored: git's autocrlf rewrites them on checkout,
    # which isn't a content change.
    return "ok" if have.replace("\r\n", "\n") == want.replace("\r\n", "\n") else "stale"


def status(rel, config, page_html, wanted=True):
    """'ok', 'missing', 'stale', or 'unwanted' for the head block."""
    want = expected_block(rel, config, page_html) if wanted else None
    return _compare(current_block(page_html), want)


def footer_status(rel, page_html, wanted=True):
    """'ok', 'missing', 'stale', or 'unwanted' for the site footer."""
    want = expected_footer(rel, page_html) if wanted and wants_footer(page_html) else None
    return _compare(current_block(page_html, FOOT_RE), want)


def all_html():
    out = []
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
        out += [os.path.relpath(os.path.join(root, f), REPO).replace(os.sep, "/")
                for f in files if f.endswith(".html")]
    return sorted(out)


def audit():
    """[(page, what)] for every .html file in the repo whose analytics
    block or site footer isn't ok, e.g. ("x/index.html", "stale analytics block")."""
    want = targets()
    issues = []
    for rel in all_html():
        page = read_page(_abs(rel))
        st = status(rel, want.get(rel), page, wanted=rel in want)
        if st != "ok":
            issues.append((rel, f"{st} analytics block"))
        st = footer_status(rel, page, wanted=rel in want)
        if st != "ok":
            issues.append((rel, f"{st} site footer"))
    return issues


def ungated_tags():
    """Pages loading anything from googletagmanager.com outside the managed
    block, i.e. a hand-pasted Google tag that ignores the visitor's choice."""
    return [rel for rel in all_html() if GTM_RE.search(BLOCK_RE.sub("", read_page(_abs(rel))))]


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
    if not os.path.isfile(_abs(PRIVACY_PAGE)):
        print(f"  WARNING: {PRIVACY_PAGE} is missing (the banner and footer link to it)")
    print(f"Needing changes: {len(issues)}")
    counts = {}
    for rel, what in issues:
        counts[what] = counts.get(what, 0) + 1
    if counts:
        print("  " + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())))
    for rel in untracked_links():
        print(f"  WARNING: no outbound a.shop link to track on {rel}")
    for rel in ungated_tags():
        print(f"  WARNING: googletagmanager.com loaded outside the consent gate on {rel} (remove it by hand)")
    if args.check or not issues:
        return
    for rel in sorted({rel for rel, _ in issues}):
        page = read_page(_abs(rel))
        wanted = rel in want
        page = apply(page, expected_block(rel, want.get(rel), page) if wanted else None)
        page = apply_footer(page, expected_footer(rel, page) if wanted and wants_footer(page) else None)
        write_page(_abs(rel), page)
    print(f"Updated {len({rel for rel, _ in issues})} page(s).")


if __name__ == "__main__":
    main()
