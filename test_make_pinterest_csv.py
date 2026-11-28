"""Unit tests for the UTM tagging and Awin disclosure in make_pinterest_csv.py.

Run: py -3 -m unittest test_make_pinterest_csv
(No network: nothing here fetches a URL.)
"""

import unittest
import urllib.parse

import make_pinterest_csv as m

SITE = m.SITE
CAMPAIGN = "2026-11-23"


def pin(type_, id_, link):
    return {"type": type_, "id": id_, "link": link}


def query(url):
    return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))


class UtmLinkTests(unittest.TestCase):
    def test_outfit(self):
        p = pin("outfit", "gameday/gameday-nov-23-2", SITE + "outfits/gameday/gameday-nov-23-2/")
        url = m.utm_link(p, CAMPAIGN)
        self.assertTrue(url.startswith(SITE + "outfits/gameday/gameday-nov-23-2/?"))
        self.assertEqual(query(url), {"utm_source": "pinterest", "utm_medium": "social",
                                      "utm_campaign": CAMPAIGN,
                                      "utm_content": "gameday-nov-23-2-outfit",
                                      "utm_term": "outfit"})

    def test_product(self):
        p = pin("product", "trending-products/trending-products-nov-23/pea-coat",
                SITE + "outfits/trending-products/trending-products-nov-23/pea-coat/")
        self.assertEqual(query(m.utm_link(p, CAMPAIGN))["utm_content"],
                         "trending-products-nov-23-pea-coat")

    def test_gift_keeps_fragment_after_query(self):
        p = pin("gift", "N163", SITE + "gift-guide/#N163")
        url = m.utm_link(p, CAMPAIGN)
        parts = urllib.parse.urlsplit(url)
        self.assertEqual(parts.fragment, "N163")
        self.assertTrue(url.endswith("#N163"))
        self.assertEqual(url.count("?"), 1)
        self.assertEqual(query(url)["utm_content"], "gift-guide-n163")

    def test_existing_query_no_double_question_mark(self):
        p = pin("product", "a/b-c/d", SITE + "outfits/a/b-c/d/?ref=x&utm_source=old")
        url = m.utm_link(p, CAMPAIGN)
        self.assertEqual(url.count("?"), 1)
        q = query(url)
        self.assertEqual(q["ref"], "x")
        self.assertEqual(q["utm_source"], "pinterest")

    def test_idempotent(self):
        p = pin("outfit", "casual/casual-outfit-nov-23", SITE + "outfits/casual/casual-outfit-nov-23/")
        once = m.utm_link(p, CAMPAIGN)
        p["link"] = once
        self.assertEqual(m.utm_link(p, CAMPAIGN), once)

    def test_slug_lowercase_hyphens_only(self):
        self.assertEqual(m.slug("Gameday_Nov 23!!"), "gameday-nov-23")
        p = pin("product", "Gift-Guides/Holiday_2026/Moto Boots", SITE + "gift-guide/")
        self.assertRegex(m.utm_content(p), r"^[a-z0-9]+(-[a-z0-9]+)*$")

    def test_affiliate_links_untouched(self):
        for link in ("https://www.amazon.com/dp/B000000000?tag=thatfootbal01-20",
                     "https://ca.shein.com/x-p-123.html",
                     "https://www.awin1.com/cread.php?awinmid=1&p=x"):
            p = pin("product", "a/b/c", link)
            self.assertEqual(m.utm_link(p, CAMPAIGN), link)

    def test_length(self):
        p = pin("product", "trending-products/trending-products-nov-23-3/relaxed-fit-ribbed-knit-sweater",
                SITE + "outfits/trending-products/trending-products-nov-23-3/relaxed-fit-ribbed-knit-sweater/")
        self.assertLess(len(m.utm_link(p, CAMPAIGN)), 500)


class ValidateUtmTests(unittest.TestCase):
    def problems(self, pins, tagged=True):
        out = []
        m.validate_utm(pins, CAMPAIGN, out, tagged)
        return out

    def test_tagged_hub_link_passes(self):
        p = pin("outfit", "gameday/gameday-nov-23", SITE + "outfits/gameday/gameday-nov-23/")
        p["link"] = m.utm_link(p, CAMPAIGN)
        self.assertEqual(self.problems([p]), [])

    def test_hub_link_without_utm_fails(self):
        p = pin("outfit", "gameday/gameday-nov-23", SITE + "outfits/gameday/gameday-nov-23/")
        self.assertEqual(len(self.problems([p])), 1)

    def test_hub_link_wrong_campaign_fails(self):
        p = pin("outfit", "gameday/gameday-nov-23", SITE + "outfits/gameday/gameday-nov-23/")
        p["link"] = m.utm_link(p, "2026-11-16")
        self.assertIn("utm_campaign", self.problems([p])[0])

    def test_untagged_batch_plain_hub_link_passes(self):
        p = pin("outfit", "gameday/gameday-nov-16", SITE + "outfits/gameday/gameday-nov-16/")
        self.assertEqual(self.problems([p], tagged=False), [])

    def test_affiliate_link_with_utm_fails(self):
        p = pin("product", "a/b/c", "https://www.amazon.com/dp/B000000000?tag=thatfootbal01-20"
                                    "&utm_source=pinterest")
        out = self.problems([p])
        self.assertEqual(len(out), 1)
        self.assertIn("affiliate", out[0])
        # ...even in a batch before UTM_FROM.
        self.assertEqual(len(self.problems([p], tagged=False)), 1)

    def test_affiliate_link_without_utm_passes(self):
        p = pin("product", "a/b/c", "https://ca.shein.com/x-p-123.html")
        self.assertEqual(self.problems([p]), [])



# --- thin-section routing (pin_routing.py) --------------------------------

import json
import os

import pin_routing as r

SETTINGS = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "pinterest", "pin_settings.json"), encoding="utf-8"))
CATS = {"fan_gear": {"include": [], "exclude": [], "licensed_keywords": ["nfl"],
                     "licensed_brands": [], "teams": []}}


def item(price, name="Plain Item", item_type="Bottoms", theme="casual", currency="CAD",
         retailer="SHEIN", id_="x/y/z"):
    return {"id": id_, "price": price, "currency": currency, "name": name,
            "item_type": item_type, "theme": theme, "retailer": retailer}


def rpin(type_, id_, board, section, items, **kw):
    p = {"type": type_, "id": id_, "board": board, "section": section,
         "title": id_, "items": items}
    if type_ == "product":
        p["rec"] = items[0]
    p.update(kw)
    return p


def zero_counts():
    return {k: 0 for k in r.thin_keys(SETTINGS["routing"])}


class RoutingTests(unittest.TestCase):
    FALL = "Fall Casual Outfits for Men"
    GAME = "Game Day Outfits for Men"
    STADIUM = "Men's Stadium Streetwear"

    def route(self, pins, counts=None):
        counts = counts if counts is not None else zero_counts()
        r.route(pins, SETTINGS, counts, apply=True, cat_cfg=CATS)
        return counts

    def test_outfit_total_tiers_boundary(self):
        under = rpin("outfit", "casual/a", self.FALL, "Weekend Fall Fits", [item(30), item(19.99)])
        at = rpin("outfit", "casual/b", self.FALL, "Weekend Fall Fits", [item(30), item(20)])
        self.route([under, at])
        self.assertEqual(under["section"], "Under $50")             # 49.99
        self.assertEqual(at["section"], "Splurge Worthy ($50+)")    # 50.00

    def test_no_total_keeps_hand_section(self):
        p = rpin("outfit", "casual/c", self.FALL, "Weekend Fall Fits",
                 [item(30), item(None, retailer="Amazon", currency=None)])
        self.route([p])
        self.assertEqual(p["section"], "Weekend Fall Fits")

    def test_wrong_tier_always_corrected(self):
        p = rpin("outfit", "casual/d", self.FALL, "Under $50", [item(80)])
        counts = zero_counts()
        counts[(self.FALL, "Splurge Worthy ($50+)")] = 10   # full, still corrected
        self.route([p], counts)
        self.assertEqual(p["section"], "Splurge Worthy ($50+)")

    def test_full_thin_section_keeps_hand(self):
        p = rpin("outfit", "casual/e", self.FALL, "Weekend Fall Fits", [item(80)])
        counts = zero_counts()
        counts[(self.FALL, "Splurge Worthy ($50+)")] = 10
        self.route([p], counts)
        self.assertEqual(p["section"], "Weekend Fall Fits")

    def test_fewest_pins_wins(self):
        rec = item(15, name="Fleece Gym Shorts")
        p = rpin("product", "a/b/shorts", "Men's Basics & Essentials", "Pants", [rec])
        counts = zero_counts()
        counts[("Men's Basics & Essentials", "Under $20")] = 4
        self.route([p], counts)
        self.assertEqual(p["section"], "Shorts")

    def test_running_keyword(self):
        p = rpin("product", "a/b/shoes", "Men's Fall Style Essentials", "Fall Footwear",
                 [item(40, name="Mesh Running Shoes", item_type="Footwear")])
        self.route([p])
        self.assertEqual((p["board"], p["section"]), ("Men's Gym & Training Outfits", "Running"))

    def test_streetwear_splurge(self):
        p = rpin("outfit", "motor-streetwear/m", "Men's Fall Streetwear 2026",
                 "Fall Layered Streetwear", [item(60)])
        self.route([p])
        self.assertEqual(p["section"], "Splurge Worthy ($50+)")

    def test_one_in_three_gameday_to_stadium(self):
        pins = [rpin("outfit", f"gameday/g{i}", self.GAME, "Team Gear", [item(80)]) for i in range(4)]
        pins.insert(1, rpin("outfit", "gameday/h", self.GAME, "Hockey Night", [item(80)]))
        self.route(pins)
        moved = [p["id"] for p in pins if p["board"] == self.STADIUM]
        self.assertEqual(moved, ["gameday/g0", "gameday/g3"])
        self.assertEqual(pins[0]["section"], "Team Colours")

    def test_stadium_off_duty_and_under_50(self):
        fan = rpin("outfit", "gameday/f", self.GAME, "", [item(90, name="NFL Hoodie")])
        cheap = rpin("outfit", "gameday/c", self.GAME, "", [item(40)], outfit_check=True)
        counts = zero_counts()
        counts[(self.STADIUM, "Team Colours")] = 1   # a tie would keep Team Colours
        self.route([fan, cheap], counts)
        self.assertEqual((fan["board"], fan["section"]), (self.STADIUM, "Off Duty"))
        self.assertEqual((cheap["board"], cheap["section"]), (self.STADIUM, "Under $50"))

    def test_section_locked(self):
        p = rpin("outfit", "casual/f", self.FALL, "Weekend Fall Fits", [item(80)], section_locked=True)
        self.route([p])
        self.assertEqual(p["section"], "Weekend Fall Fits")

    def test_not_applied_counts_real_section(self):
        p = rpin("outfit", "casual/g", self.FALL, "Weekend Fall Fits", [item(80)])
        counts = zero_counts()
        d = r.route([p], SETTINGS, counts, apply=False, cat_cfg=CATS)
        self.assertEqual(p["section"], "Weekend Fall Fits")
        self.assertEqual(d[0]["to"], (self.FALL, "Splurge Worthy ($50+)"))
        self.assertEqual(counts[(self.FALL, "Splurge Worthy ($50+)")], 0)

    def test_routed_sections_exist_in_settings(self):
        boards = SETTINGS["boards"]
        for board, section in r.thin_keys(SETTINGS["routing"]):
            self.assertIn(section, boards[board])


class AwinDisclosureTests(unittest.TestCase):
    SETTINGS = {
        "disclosure": "As a SHEIN Affiliate and Amazon Associate, I earn.",
        "disclosure_shein_only": "As a SHEIN Affiliate, I earn.",
        "disclosure_awin": "As a SHEIN Affiliate, Amazon Associate and House of Blanks affiliate, I earn.",
        "disclosure_awin_only": "As a House of Blanks affiliate, I earn.",
        "disclosure_awin_amazon": "As an Amazon Associate and House of Blanks affiliate, I earn.",
        "disclosure_awin_shein": "As a SHEIN Affiliate and House of Blanks affiliate, I earn.",
    }

    def awin_pin(self, *merchants, others=()):
        items = [{"retailer": "Awin", "merchant": m_} for m_ in merchants]
        items += [{"retailer": r} for r in others]
        return {"retailers": {i["retailer"] for i in items}, "items": items}

    def test_house_of_blanks_unchanged(self):
        self.assertEqual(m.disclosure(self.awin_pin("House of Blanks"), self.SETTINGS),
                         "As a House of Blanks affiliate, I earn.")

    def test_moosehill_named(self):
        self.assertEqual(m.disclosure(self.awin_pin("Moosehill"), self.SETTINGS),
                         "As a Moosehill affiliate, I earn.")

    def test_two_merchants_with_shein(self):
        self.assertEqual(m.disclosure(self.awin_pin("Moosehill", "House of Blanks", others=["SHEIN"]),
                                      self.SETTINGS),
                         "As a SHEIN Affiliate and House of Blanks and Moosehill affiliate, I earn.")

    def test_merchants_listed(self):
        self.assertEqual(m.awin_merchants(self.awin_pin("Moosehill", "Moosehill")), ["Moosehill"])
        self.assertEqual(m.awin_merchants({"items": [{"retailer": "Awin"}]}), ["?"])


class OutfitCardTests(unittest.TestCase):
    """Outfit cards resolve to records: detail pages anywhere on the site,
    and gift guide listings (no detail page) by their tile's anchor."""
    PRODUCTS = [
        {"id": "a", "detail_page_url": "videos/x/camp/hoodie/index.html"},
        {"id": "g1", "detail_page_url": "gift-guide/index.html", "holiday_pin": "N130"},
        {"id": "g2", "detail_page_url": "gift-guide/index.html", "holiday_pin": "N129"},
    ]

    def test_detail_page_and_gift_anchor(self):
        import gift_guide
        found, missing = gift_guide.card_records(
            "outfits/gameday/gameday-nov-30",
            ["../../../videos/x/camp/hoodie/", "../../../gift-guide/#N130", "../../../gift-guide/#n0130"],
            self.PRODUCTS)
        self.assertEqual([p["id"] for p in found], ["a", "g1"])
        self.assertEqual(missing, [])

    def test_unknown_cards_reported(self):
        import gift_guide
        found, missing = gift_guide.card_records(
            "outfits/gameday/gameday-nov-30", ["../../../gift-guide/", "../../../gift-guide/#N999", "../nope/"],
            self.PRODUCTS)
        self.assertEqual(found, [])
        self.assertEqual(len(missing), 3)



class GiftRealPhotoTests(unittest.TestCase):
    """Gift pins are AI images, except a card whose record says
    "ai_image": false: that one uses <id>_photo.jpg and gets no AI line."""

    def test_gift_record_by_holiday_pin_then_image(self):
        products = [
            {"id": "a", "detail_page_url": "gift-guide/index.html", "image": "gift-guide/img/N5_x-500.jpg"},
            {"id": "b", "detail_page_url": "gift-guide/index.html", "holiday_pin": "N06", "image": None},
            {"id": "c", "detail_page_url": "videos/x/index.html", "image": "gift-guide/img/N7_y-500.jpg"},
        ]
        self.assertEqual(m.gift_record(products, "N5")["id"], "a")
        self.assertEqual(m.gift_record(products, "N6")["id"], "b")
        self.assertIsNone(m.gift_record(products, "N7"))  # not a gift guide listing

    def _resolve(self, card):
        with open(os.path.join(m.REPO, "products.json"), encoding="utf-8") as f:
            products = json.load(f)
        with open(os.path.join(m.REPO, "pinterest", "pin_settings.json"), encoding="utf-8") as f:
            settings = json.load(f)
        p, problems = {"type": "gift", "id": card}, []
        ok = m.resolve(p, products, {x["id"]: x for x in products}, settings, problems, [])
        self.assertTrue(ok, problems)
        return p

    def test_real_photo_card_uses_photo_pin_without_ai(self):
        p = self._resolve("N184")
        self.assertFalse(p["ai"])
        self.assertTrue(p["media"].endswith("holiday-2026/pins/N184_photo.jpg"))

    def test_other_gift_cards_stay_ai(self):
        p = self._resolve("N185")
        self.assertTrue(p["ai"])
        self.assertTrue(p["media"].endswith("holiday-2026/pins/N185_gift.jpg"))

if __name__ == "__main__":
    unittest.main()
