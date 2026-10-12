# CLAUDE.md

Guidance for Claude Code (and other agents) working in this repo.

## Repo root redirect stubs

The repo root contains ~70 folders whose names look like campaign slugs
(e.g. `casual-august1/`, `business-casual-aug-10/`, `eagles-broncos/`)
but sit outside both `outfits/` and `videos/`. **These are intentional
redirect stubs that keep pre-restructure Pinterest links working** —
they are not build leftovers, orphaned artifacts, or duplicates to clean
up. Do not delete, move, or modify them, in this task or in any later
cleanup pass, without explicit instruction to do so. The one sanctioned
edit is the `<!-- favicons:start/end -->` block that `add_favicons.py`
maintains in their `<head>` (added on explicit instruction); leave it
there.

## Weekly batch checklist

Run `python sync_catalog.py` as the last step of every weekly batch,
before committing. Nothing in the batch pipeline (`parse_shein.py` ->
`classify.py` -> `fetch_images.py` -> `build_outfits.py`) touches
`products.json` — those four scripts only get you to a proposed outfit
grouping in `outfits.csv`. Someone still hand-creates the actual outfit
directories, downloads photos, writes the detail pages, and inserts
category-page cards, and it's easy to finish that step without also
updating the catalog. That's exactly what happened to the Sept 15
business-casual, old-money, and streetwear batches — nine products with
complete, live pages that never appeared in the shop grid until caught
weeks later. `sync_catalog.py` scans `outfits/` and `videos/` for detail
pages missing a `products.json` record (plus the reverse: stale records
whose page no longer exists, and records with a missing thumbnail) and
reports them. Pass `--append` to add the missing records automatically —
it still flags `item_type` and `data_new` for manual review on every new
record, since neither has a reliable source outside human judgment.
New records get an `added` date from the campaign slug.
Items 1 and 2 (page with no record, record with no page) make the script
exit 1, and the `catalog-check.yml` workflow runs it on every push and
PR to main, so a batch that skips this step fails CI.

**New item_type? Add it to `categories.json`.** The products page
(`products/`) puts every product in a tab (Outerwear, Tops, Bottoms,
Footwear, Accessories, Fan Gear) and a sub-chip using the rules in
`categories.json`: `item_types` maps each `item_type` to a tab, and
keywords in the product name pick the sub-chip. `sync_catalog.py`
report item 10 fails (exit 1, so CI fails) when any record's
`item_type` isn't listed in `item_types`, so a batch can't land with
products that have no tab. Item 10 also fails on a record with no valid
`added` date. `--append` sets `added` (YYYY-MM-DD, used by the Newest
sort) from the campaign slug's date, so check it on new records. Item 10
warns, without failing, about any product whose name has a team name
but nothing that shows it's licensed (add its id to `fan_gear.include`
or `fan_gear.exclude`), and about any product that matches no
sub-chip (add a keyword, or an `overrides` entry). Fan Gear is
officially licensed items only. To take a product off the products page
but keep its detail page live (old pins still work), add its id to
`hidden`. Run `py -3 categories.py` to see every tab and sub-chip with
its count.

Then run `python add_product_schema.py` (after any `--append`, since it
reads `products.json`). It writes the schema.org Product JSON-LD block
into every SHEIN detail page's `<head>` between
`<!-- product-schema:start/end -->` markers, and refreshes any block
whose price, description, or link has changed. Amazon and Awin pages
deliberately get no block (no price is shown on them, so there's nothing
to mark up), and neither do `image_pending` pages until their photo
exists (Google treats a Product without `image` as an invalid merchant
listing). `sync_catalog.py`'s report item 4 flags any page whose
block is missing or stale, so a clean `sync_catalog.py` run means the
schema is current too.

Then run `python add_analytics.py`. It writes the Google Analytics 4 tag
(`G-E3HV1TFPEN`) into every site page's `<head>`, right after
`<meta charset>`, between `<!-- analytics:start/end -->` markers. On
product detail pages it adds `affiliate_click` tracking for the `.shop`
link, with parameters from the page's `products.json` record (value and
currency for SHEIN only). On legacy link-list campaign pages and the
homepage it tracks the `.link-card`/`.affiliate-banner` links from their
domain and text. New batch pages and changed product records get picked
up automatically. It deliberately leaves out `archive/`, the root
redirect stubs, and the `googlec…html` Search Console file.
The tag is consent-gated: gtag.js doesn't load until the visitor clicks
Accept on the cookie banner, and the same script writes a site footer
(`<!-- site-footer:start/end -->`, before `</body>`) with the affiliate
disclosure, a link to `privacy/`, and a "Cookie settings" button to
change the choice. Never paste a raw Google tag into a page: it would
load regardless of the visitor's choice, and report item 6 flags it.
If `privacy/index.html` changes materially, bump `CONSENT_VERSION` in
`add_analytics.py` so every visitor gets asked again.
`sync_catalog.py`'s report item 6 flags any page whose block is missing
or stale, and any detail page with no outbound `.shop` link.

Then run `python add_favicons.py`. It writes the favicon and
apple-touch-icon `<link>` tags (icons in `assets/icons/`, relative
hrefs) right before `</head>` on every page, root redirect stubs and
`archive/` included, between `<!-- favicons:start/end -->` markers. A
new page copied from an existing one already carries the block, and the
script corrects its relative path if the new page sits at a different
depth. `sync_catalog.py`'s report item 9 flags any page whose block is
missing or stale.

Then run `python write_sitemap.py` and commit the regenerated
`sitemap.xml` with the batch. It lists the homepage, the shop grid,
every category and campaign page, and every product detail page in
`products.json`, and leaves out redirect pages (the root redirect
stubs and retired campaign pages, detected by their meta refresh) and
`archive/`. `<lastmod>` comes from each file's last git commit, with
today's date for anything not committed yet, so running it right before
the batch commit gives new pages the batch date. `sync_catalog.py`'s
report item 5 flags pages missing from `sitemap.xml`, entries whose
page is gone, and out-of-date `<lastmod>` dates.

So the order is: `sync_catalog.py` (plus `--append` if needed, then set
`item_type`/`data_new`, check `added`, and add any new item_type to
`categories.json`), then `add_product_schema.py`, then `add_analytics.py`, then
`add_favicons.py`, then `write_sitemap.py` last among the writers (the
scripts before it edit
pages, and each edit moves that page's `<lastmod>`), then
`sync_catalog.py` once more to confirm it's clean.

Once the batch's outfit photos are wired up (and its `products.json`
records exist, since the price comes from there), run
`py -3 make_outfit_pin.py --batch <date>` (e.g. `--batch oct-12`, which
also covers `-oct-12-2`, `-oct-12-3`, ...). It writes the Pinterest pin
image `outfit-pin.jpg` into each campaign folder from its
`outfit-preview.*`, with the price overlay that used to be added by hand
in Gemini: "UNDER $X!" from the outfit's total rounded up to the next
$5, or "FULL FIT ↓" when any item has no stored price (Amazon, Awin),
under "SHOP THE LOOK" ("ON SALE NOW" if any item has a discount). The
site keeps using the plain `outfit-preview`, which the script never
modifies. It prints one line per pin naming the path it took:
`overlay` (text in a fade over the photo's own floor) or `shrink` (photo
shrunk onto a 2:3 canvas with the text in new space below it).
`outfit-preview` must be the clean Gemini photo with NO text on it: the
script adds its own, so a preview with a baked-in price ends up with two
(most oct-5 and oct-12 previews have one). New Gemini photos should be
2:3, full body, head to shoes, filling about 85–90% of the image
height. That framing leaves no floor for the text, so these pins take
the `shrink` path.
Commit the `outfit-pin.jpg` files with the batch: their URLs on the
live site are the public Media URLs for the Pinterest bulk upload.

Once the batch is wired up (product photos in place and `products.json`
records written, since the price comes from there), run
`py -3 make_product_pin.py --pick 20 --batch <date>` (e.g.
`--batch oct-12`, which also covers `-oct-12-2`, `-oct-12-3`, ...). It
picks the batch's 20 best SHEIN deals (any with `discount_percent` of
20 or more first, biggest discount first, then the rest cheapest first;
smaller discounts don't count), prints the list, and writes the
Pinterest pin `product-pin.jpg` into each product's folder: a 1000x1500
pin with the product photo above "SHOP NOW" / "UNDER $X!" (the price
rounded up: to the next dollar under $10, else to the next $5). Amazon
and Awin products, products with no price, and `image_pending` products
are skipped. The product's own photo is never modified. Add `--dry-run`
to see the list without writing anything. Commit the `product-pin.jpg`
files with the batch: their URLs on the live site are the public Media
URLs for the Pinterest bulk upload.

Once the batch (with its `outfit-pin.jpg` and `product-pin.jpg` files)
is merged and live, write the pin copy into
`pinterest/pins_<date>.json` and run
`py -3 make_pinterest_csv.py <date>` (e.g. `oct-19`). It builds
`pinterest/pinterest_bulk_<date>.csv` in Pinterest's bulk-upload
template layout (split into `_1`, `_2`, ... over Pinterest's 200-row
limit) plus `pinterest_bulk_<date>_report.md`. The description is the
copy + the disclosure from `pinterest/pin_settings.json` (the
SHEIN-only wording when every item in the pin is SHEIN, else the
SHEIN + Amazon one) (+ "Image created with AI." on every outfit pin and
Amazon product pin) + the hashtags. Pins are scheduled across the batch week (Mon–Sun), 2 outfit
pins a day with gameday first, product pins filling the days evenly,
08:00–21:00 Atlantic, written as UTC (Pinterest reads Publish date as
UTC). It validates everything first and writes no CSV if anything
fails: every Link and Media URL must return 200 on the live site (so
the pin images must be pushed first), titles ≤ 100 and full
descriptions ≤ 500 characters, no duplicates, no past publish times,
no "$" in the copy of a pin with an Amazon item, no retailer the
disclosures don't cover (Awin needs its own wording first), and every board and
section must be listed in `pin_settings.json`. Keep that list identical
to the Pinterest account, emojis included: Pinterest silently creates
any board or section it doesn't recognise. The CSV has no column for
alt text or the AI-modified label, so the report lists both to add by
hand after upload. `--dry-run` validates and prints the report without
writing anything.

When a page needs a photo that has to be sourced by hand at the
campaign level (e.g. a wrong or missing `outfit-preview.jpg`, which no
`products.json` field tracks), leave an HTML comment containing
`PHOTO NEEDED` at the spot. `sync_catalog.py` report item 7 lists every
one, and its summary line keeps naming them until the comment is
removed along with the fix.

Working-file commits (`batch.txt`, `parsed_products.csv`,
`classified_products.csv`, `outfits.csv`) must blank the `price` of
every Amazon row and the `total_price` of any outfit that includes an
Amazon item. The repo is the live Pages site, so those CSVs are public.
