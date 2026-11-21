"""Unit tests for the UTM tagging in make_pinterest_csv.py.

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


if __name__ == "__main__":
    unittest.main()
