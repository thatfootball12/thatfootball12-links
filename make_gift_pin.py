#!/usr/bin/env python3
"""
Makes a headline gift pin from a clean AI photo in holiday-2026/pins/:
<id>_ai.jpg becomes <id>_gift.jpg, with "MEN'S GIFT GUIDE" over a short
headline in the make_product_pin.py style. No price, number or deal
wording, so it's safe for Amazon. The source photo is never written to.

Usage:
    py -3 make_gift_pin.py N74 N78 ...                (GIFT IDEA FOR HIM)
    py -3 make_gift_pin.py --use N100 N72 ...         (THE GIFT HE'LL USE)
    py -3 make_gift_pin.py N74 --photo new.jpg        (from another photo)
"""

import argparse
import os

import gift_guide
import make_product_pin as pin

HEADLINES = {False: [("GIFT IDEA ", pin.WHITE), ("FOR HIM", pin.GOLD)],
             True: [("THE GIFT ", pin.WHITE), ("HE'LL USE", pin.GOLD)]}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    ap.add_argument("cards", nargs="+", help="gift guide card ids, e.g. N74")
    ap.add_argument("--use", action="store_true", help="THE GIFT HE'LL USE headline")
    ap.add_argument("--photo", help="source photo instead of <id>_ai.jpg (one card only)")
    args = ap.parse_args()
    if args.photo and len(args.cards) > 1:
        ap.error("--photo takes one card")
    runs = (("MEN'S GIFT GUIDE", pin.WHITE), HEADLINES[args.use])
    for card in args.cards:
        base = os.path.join(pin.REPO, gift_guide.PIN_DIR, card)
        img, path = pin.render(args.photo or base + "_ai.jpg", None, runs)
        img.save(base + "_gift.jpg", "JPEG", quality=88, optimize=True, progressive=True)
        print(f"made  {gift_guide.PIN_DIR}/{card}_gift.jpg [{path}]")


if __name__ == "__main__":
    main()
