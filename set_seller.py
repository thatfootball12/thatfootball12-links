#!/usr/bin/env python3
"""
Records who sells a SHEIN product (the products.json "seller" field; see
sellers.py), then rewrites unchecked_sellers.txt.

Usage:
    py -3 set_seller.py <id> shein            (sold by SHEIN)
    py -3 set_seller.py <id> marketplace      (third-party store)
    py -3 set_seller.py <id> <value> <id> <value> ...
    py -3 set_seller.py --from results.txt    (bulk, see below)
    py -3 set_seller.py --list                (just rewrite unchecked_sellers.txt)

--from FILE ("-" for stdin): one product per line, the products.json id
first and the value (shein, marketplace or unchecked) anywhere after it,
so lines copied from unchecked_sellers.txt work with the value added to
the end. Blank lines and lines starting with # are skipped.

Nothing is written if any line has an unknown id, a non-SHEIN product,
or no valid value: fix the list and run it again.
"""

import argparse
import json
import os
import sys

import sellers

REPO = os.path.dirname(os.path.abspath(__file__))
PRODUCTS_JSON = os.path.join(REPO, "products.json")


def parse_lines(lines, source):
    pairs, problems = [], []
    for n, line in enumerate(lines, 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        tokens = line.split()
        values = [t for t in tokens[1:] if t.lower() in sellers.VALUES]
        if len(values) != 1:
            problems.append(f"{source}:{n}: need exactly one of {', '.join(sellers.VALUES)} "
                            f"after the id: {line}")
            continue
        pairs.append((tokens[0], values[0].lower()))
    return pairs, problems


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    ap.add_argument("pairs", nargs="*", metavar="ID VALUE", help="products.json id, then shein|marketplace")
    ap.add_argument("--from", dest="source", metavar="FILE", help="file of '<id> ... <value>' lines (- for stdin)")
    ap.add_argument("--list", action="store_true", help="only rewrite unchecked_sellers.txt")
    args = ap.parse_args()

    if len(args.pairs) % 2:
        ap.error("give ids and values in pairs: <id> <shein|marketplace> ...")
    pairs = [(args.pairs[i], args.pairs[i + 1].lower()) for i in range(0, len(args.pairs), 2)]
    problems = [f"{pid}: value {v!r} isn't one of {', '.join(sellers.VALUES)}"
                for pid, v in pairs if v not in sellers.VALUES]
    if args.source:
        if args.source == "-":
            more, bad = parse_lines(sys.stdin.read().splitlines(), "stdin")
        else:
            with open(args.source, encoding="utf-8-sig") as f:
                more, bad = parse_lines(f.read().splitlines(), args.source)
        pairs += more
        problems += bad
    if not pairs and not args.list:
        ap.error("give <id> <value> pairs, --from FILE, or --list")

    with open(PRODUCTS_JSON, encoding="utf-8") as f:
        products = json.load(f)
    by_id = {p["id"]: p for p in products}

    seen = {}
    for pid, v in pairs:
        p = by_id.get(pid)
        if p is None:
            problems.append(f"{pid}: not in products.json")
        elif not sellers.is_shein(p):
            problems.append(f"{pid}: {p.get('retailer')} product; seller is SHEIN only")
        elif pid in seen and seen[pid] != v:
            problems.append(f"{pid}: listed as both {seen[pid]} and {v}")
        seen[pid] = v
    if problems:
        print(f"{len(problems)} problem(s), nothing written:")
        for msg in problems:
            print(f"  - {msg}")
        return 1

    changed = 0
    for pid, v in seen.items():
        p = by_id[pid]
        old = p.get("seller")
        if old == v:
            print(f"same  {pid}: {v}")
            continue
        if "seller" in p:
            p["seller"] = v
        else:
            # Keep it beside retailer, where the rest of the catalog has it.
            items = list(p.items())
            at = next((i + 1 for i, (k, _) in enumerate(items) if k == "retailer"), len(items))
            items.insert(at, ("seller", v))
            p.clear()
            p.update(items)
        print(f"set   {pid}: {old or '(none)'} -> {v}")
        changed += 1

    if changed:
        with open(PRODUCTS_JSON, "w", encoding="utf-8") as f:
            json.dump(products, f, indent=2, ensure_ascii=False)
    left = sellers.write_unchecked(products)
    _, counts = sellers.audit(products)
    print(f"\n{changed} record(s) changed. Sellers: {counts['shein']} shein, "
          f"{counts['marketplace']} marketplace, {counts['unchecked']} unchecked "
          f"({left} listed in unchecked_sellers.txt).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
