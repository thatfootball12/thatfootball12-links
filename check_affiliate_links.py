#!/usr/bin/env python3
"""
Checks every outbound_url in products.json and reports which affiliate
links are dead versus inconclusive (bot-blocked/timed out, not actually
verified dead). Never modifies products.json or any page — this is a
report-only tool. Meant to run weekly via
.github/workflows/affiliate-link-check.yml, which opens or updates a
single GitHub issue with the results.

Usage:
    python3 check_affiliate_links.py            (writes report.md, prints summary)

Detection approach (see the weekly-link-checker branch's PR description
for the investigation this is based on):

  - Amazon (amazon.com/amazon.ca/amzn.to) and Awin (tidd.ly/awin1.com):
    plain GET request following redirects. Amazon's servers reject HEAD
    with 405 across the board (confirmed empirically against ~90 live
    links) — GET is required, not just kinder.

  - SHEIN (onelink.shein.com): these are NOT server-side HTTP redirects.
    A GET returns 200 with an HTML interstitial page containing
    <input id="url" value="...">, and a script does
    `window.location.href = url` client-side. So:
      1. GET the onelink.shein.com page, extract that embedded URL.
      2. Check it matches SHEIN's product-page pattern (-p-<digits>-cat-
         <digits>.html). If it doesn't — e.g. it points at a generic
         `api-shein.shein.com/h5/sharejump/...` page instead — the link
         no longer leads to a product. Treat as DEAD.
      3. If it does match, GET that destination URL too and check its
         status (catches a plain 404 on a delisted product ID).

    Known limitation, deliberately not solved here: a sold-out-but-still-
    listed SHEIN product returns 200 with a normal-looking product URL,
    but the actual page content (stock status) only renders after
    JavaScript executes — a plain HTTP request gets a generic client-
    rendered shell (confirmed empirically: even a known-live product
    returns SHEIN's homepage title/no og:type via plain GET). Detecting
    "sold out but listed" would need a headless browser (Playwright),
    which is a heavier, slower, more fragile addition than this script
    takes on. If silent sold-out items turn out to be a real problem in
    practice, that's the next thing to add.

Verdicts:
  - OK: the link resolves to a live destination.
  - DEAD: confirmed 404/410, or a SHEIN link that no longer leads to a
    product page at all.
  - INCONCLUSIVE: 403/429 or a timeout/connection error. Both Amazon and
    SHEIN block automated requests sometimes — a false "dead" report from
    a momentary block is worse than no report, so these are never counted
    as dead.
"""

import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

REPO = os.path.dirname(os.path.abspath(__file__))
PRODUCTS_JSON = os.path.join(REPO, "products.json")
REPORT_PATH = os.path.join(REPO, "link_check_report.md")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
TIMEOUT = 12
THROTTLE = 1.5

SHEIN_URL_INPUT_RE = re.compile(r'<input id="url" value="([^"]+)"')
SHEIN_PRODUCT_PATTERN_RE = re.compile(r"-p-\d+-cat-\d+\.html")


def classify_domain(url):
    u = url.lower()
    if "amazon.com" in u or "amazon.ca" in u or "amzn.to" in u:
        return "amazon"
    if "onelink.shein.com" in u:
        return "shein"
    return "other"


def get(url):
    """GET (never HEAD — Amazon rejects HEAD with 405). Returns
    (status, final_url, body_or_None, error_or_None)."""
    req = urllib.request.Request(url, headers={"User-Agent": UA}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, resp.geturl(), body, None
    except urllib.error.HTTPError as e:
        return e.code, url, None, None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return None, None, None, str(e)


def status_verdict(status, err, context=""):
    if err is not None:
        low = err.lower()
        if "timed out" in low or "timeout" in low:
            return "INCONCLUSIVE", f"timeout{context} ({err})"
        return "INCONCLUSIVE", f"request error{context} ({err})"
    if status in (404, 410):
        return "DEAD", f"HTTP {status}{context}"
    if status in (403, 429):
        return "INCONCLUSIVE", f"HTTP {status}{context} (likely bot-blocked)"
    if status and 200 <= status < 400:
        return "OK", f"HTTP {status}{context}"
    return "INCONCLUSIVE", f"unexpected HTTP {status}{context}"


def check_generic(url):
    """Amazon and Awin: one GET, follow redirects, read the status."""
    status, _final_url, _body, err = get(url)
    return status_verdict(status, err)


def check_shein(url):
    status, _final_url, body, err = get(url)
    if err is not None or status is None:
        return status_verdict(status, err, " (onelink)")
    if status in (404, 410):
        return "DEAD", f"onelink itself returned HTTP {status}"
    if status in (403, 429):
        return "INCONCLUSIVE", f"onelink returned HTTP {status} (likely bot-blocked)"
    if status != 200:
        return "INCONCLUSIVE", f"onelink returned unexpected HTTP {status}"

    m = SHEIN_URL_INPUT_RE.search(body or "")
    if not m:
        return "INCONCLUSIVE", "could not extract destination URL from onelink interstitial"
    dest = html.unescape(m.group(1))

    if not SHEIN_PRODUCT_PATTERN_RE.search(dest):
        return "DEAD", f"redirected to a non-product URL: {dest[:120]}"

    time.sleep(THROTTLE)
    status2, _final2, _body2, err2 = get(dest)
    verdict, reason = status_verdict(status2, err2, " (destination)")
    if verdict == "OK":
        reason = f"product page confirmed ({reason})"
    return verdict, reason


def main():
    with open(PRODUCTS_JSON, encoding="utf-8") as f:
        products = json.load(f)

    by_url = {}
    for p in products:
        by_url.setdefault(p["outbound_url"], []).append(p)

    print(f"Total products: {len(products)}")
    print(f"Unique URLs to check: {len(by_url)}\n")

    results = {}
    for i, (url, plist) in enumerate(by_url.items(), 1):
        domain = classify_domain(url)
        if domain == "shein":
            verdict, reason = check_shein(url)
        else:
            verdict, reason = check_generic(url)
        results[url] = (verdict, reason, domain)
        print(f"[{i}/{len(by_url)}] {verdict:12} {domain:8} {reason[:80]}")
        time.sleep(THROTTLE)

    rows = []
    for url, (verdict, reason, domain) in results.items():
        for p in by_url[url]:
            rows.append({
                "id": p["id"], "name": p["name"], "detail_page_url": p["detail_page_url"],
                "url": url, "domain": domain, "verdict": verdict, "reason": reason,
            })

    dead = [r for r in rows if r["verdict"] == "DEAD"]
    inconclusive = [r for r in rows if r["verdict"] == "INCONCLUSIVE"]
    ok_count = sum(1 for r in rows if r["verdict"] == "OK")

    lines = []
    lines.append(f"_Checked {len(products)} products, {len(by_url)} unique outbound URLs._\n")
    lines.append(f"- OK: {ok_count}")
    lines.append(f"- Dead: {len(dead)}")
    lines.append(f"- Inconclusive: {len(inconclusive)}\n")

    lines.append("## Dead links\n")
    if dead:
        lines.append("| Product | id | Detail page | Reason |")
        lines.append("|---|---|---|---|")
        for r in dead:
            lines.append(f"| {r['name']} | `{r['id']}` | `{r['detail_page_url']}` | {r['reason']} |")
    else:
        lines.append("None.")
    lines.append("")

    lines.append("## Inconclusive (not verified dead — bot-blocked or timed out, needs a manual look)\n")
    if inconclusive:
        lines.append("| Product | id | Detail page | Reason |")
        lines.append("|---|---|---|---|")
        for r in inconclusive:
            lines.append(f"| {r['name']} | `{r['id']}` | `{r['detail_page_url']}` | {r['reason']} |")
    else:
        lines.append("None.")
    lines.append("")

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"\nOK: {ok_count}  DEAD: {len(dead)}  INCONCLUSIVE: {len(inconclusive)}")
    print(f"Report written to {REPORT_PATH}")

    # Exit code communicates to the workflow whether anything needs attention,
    # without ever touching products.json or any page.
    sys.exit(1 if dead else 0)


if __name__ == "__main__":
    main()
