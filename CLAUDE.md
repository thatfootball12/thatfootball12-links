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
Item 8 also fails CI (exit 1) when a `<picture>` WebP or its fallback JPEG is missing.
Item 13 also fails CI: any remote image on `gift-guide/index.html` fails. Every gift guide photo is self-hosted in `gift-guide/img/`, and `GIFT_GUIDE_REMOTE_ALLOWLIST` in `sync_catalog.py` is deliberately empty.

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

**New campaign? Add it to `generator.json` themes.** The Random Outfit
Generator (`generator/`) only shuffles products from campaigns listed
under one of its themes (Gameday, Date Night, Business Casual,
Streetwear, Casual) or under `unthemed` (Theme = Any only).
`sync_catalog.py` report item 11 fails (exit 1, so CI fails) when a
campaign in `products.json` isn't listed, or `generator.json` names a
campaign, category or product that doesn't exist. The slot categories,
style rules, budget tiers and exclusions live in the same file. Run
`py -3 outfit_generator.py` to see each theme's pool sizes and which
budget tiers can build an outfit (the page greys out the rest).
Out-of-season categories go in `seasonal_off` (Shorts and Sandals &
Slides are off for the winter): delete an entry to bring it back.

**`data/dead_links.json` is machine-written: don't edit it in a batch.**
The weekly `affiliate-link-check.yml` workflow runs
`check_affiliate_links.py`, which checks each SHEIN product by its plain
ca.shein.com page from `goods_id` (never the affiliate link: fetching
one counts as a click), and commits the file to main ("Update dead
links [skip ci]") when it changes. A product dead in 2 weekly runs is
`confirmed`, and the generator (page and `outfit_generator.py`) leaves
it out of every pool. SHEIN's bot check, 403/429 and timeouts are
`unknown` and never count. `sync_catalog.py` item 11 warns, without
failing, about an entry whose id is gone from `products.json` (deleting
that entry by hand is safe). The one hand edit: a product that's still
listed but SOLD OUT reads as ok to the script, so to keep it out of the
generator add a `confirmed` entry (`consecutive` 2) whose `note` starts
with `manual:`. Runs never change or remove a `manual:` entry, so delete
it by hand when the product is back in stock. Hide it from the products
page too (`categories.json` `hidden`), and take it out of both places
together. Currently sold out (remove from both `data/dead_links.json` and
`hidden` when it's back): `trending-products/trending-products-nov-2-2/yellow-wash-jeans`,
`trending-products/trending-products-oct-26-2/lace-up-boots`.

**New SHEIN product? Set its seller during sourcing.** Every SHEIN
record in `products.json` carries `seller`: `"shein"` (sold by SHEIN
itself), `"marketplace"` (a third-party store on SHEIN's marketplace),
or `"unchecked"` (nobody has looked yet; only the records that predate
the field start out this way). Amazon and Awin records have no
`seller`. When sourcing a batch, check who sells each SHEIN product on
its SHEIN page and record it with `py -3 set_seller.py <id>
shein|marketplace` (or many at once with `--from <file>`, one
`<id> ... <value>` per line). Don't leave new products `unchecked`.
`--append` gives new SHEIN records `seller: null`, and
`sync_catalog.py` report item 12 fails (exit 1, so CI fails) on any
SHEIN record whose `seller` is missing or not one of the three values,
or any Amazon/Awin record that has one; it also prints the shein /
marketplace / unchecked counts. Marketplace products never get a pin:
`make_product_pin.py` refuses them (and warns on unchecked ones), and
`make_pinterest_csv.py` blocks any product pin of one and lists
unchecked ones in its report. `set_seller.py` rewrites
`unchecked_sellers.txt` (unchecked ids, goods ids and plain SHEIN product URLs, never affiliate links, newest
batch first) on every run, so working down that file is the backlog;
`py -3 set_seller.py --list` just refreshes it. The shared rules live
in `sellers.py`, for any future pin script to import.

**Gift guide listings.** SHEIN products that appear only on the holiday
gift guide (`gift-guide/index.html`) and its pins
(`holiday-2026/pins/<pin>_holiday.png`) have no detail page, but they're
in `products.json` so the seller gates, the link checker and CI cover
them: `detail_page_url` is `gift-guide/index.html`, `holiday_pin` names
the pin (`S02` etc.), `outbound_url` and `image` are the tile's link and
photo, `price` is null, and the id is listed in `categories.json`
`hidden` (campaign `holiday-2026` sits in `generator.json` `unthemed`).
`gift_guide.py` holds the rule; the page-based scripts skip these
records, and `sync_catalog.py` report item 2 fails if a listing's tile
leaves the gift guide or its pin image goes missing. A gift guide
product whose goods_id is already in the catalog keeps that record and
just gets `holiday_pin` added. Don't create a second record for it.

Then run `python add_product_schema.py` (after any `--append`, since it
reads `products.json`). It writes the schema.org Product JSON-LD block
into every SHEIN detail page's `<head>` between
`<!-- product-schema:start/end -->` markers, and refreshes any block
whose price, description, or link has changed. Amazon and Awin pages
deliberately get no block (no price is shown on them, so there's nothing
to mark up), and neither do `image_pending` pages until their photo
exists (Google treats a Product without `image` as an invalid merchant
listing). The offer's `availability` is OutOfStock for any product
confirmed in `data/dead_links.json` (manual SOLD OUT entries
included), else InStock. The same script keeps three Rich Pin meta
tags in line on every product page: `og:title` is the short `<title>`
(without " • ThatFootball12", with a brand from `KNOWN_BRANDS` put
in front when the full name has one, e.g. "New Era 9FORTY Adjustable
Hat"), and on SHEIN pages `og:price:amount` /
`og:price:currency` copy the `product:price:*` tags and
`og:availability` follows the same sold-out rule. Don't hand-edit
those. `sync_catalog.py`'s report item 4 flags any page whose
block or those tags are missing or stale, so a clean `sync_catalog.py`
run means the schema is current too. Rerun it after a dead-links
change.

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

Then run `python add_fonts.py`. The site's fonts (Anton, Oswald,
Poppins) are self-hosted in `assets/fonts/web/` (latin WOFF2 files,
OFL licences in `assets/fonts/`), so no page contacts Google before a
cookie choice. The script writes a `<!-- fonts:start/end -->` block
(preloads plus inline `@font-face` rules, relative paths) into every
page except the redirect pages, and removes any Google Fonts `<link>`
or preconnect tag. A new page copied from an existing one already
carries the block, and the script corrects its relative paths. Never
paste a Google Fonts link into a page: `sync_catalog.py`'s report item
14 fails (exit 1, so CI fails) on any `googleapis.com` or `gstatic.com`
reference on a non-stub page, any page missing the block or with a
stale one, and any missing font file. `--check` reports without
changing anything.

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
`item_type`/`data_new`, set each new SHEIN `seller`, check `added`, and add any new item_type to
`categories.json` and any new campaign to `generator.json`), then
`add_product_schema.py`, then `build_blog.py` (see Blog below: product
cards read `products.json`, so a changed record changes posts), then
`add_analytics.py`, then
`add_favicons.py`, then `add_fonts.py`, then `write_sitemap.py` last
among the writers (the scripts before it, `add_fonts.py` included, edit
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
under "SHOP THE LOOK" ("ON SALE NOW" if any item has a discount, unless
you pass `--no-sale-line`, as the Oct 26 / Nov 2 batch did). The
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
to see the list without writing anything. `--no-inflated` leaves out
records with `inflated_original: true`, `--max-price X` anything over
$X, and `--skip <id>` (repeatable) one record; records with
`reserve: true` never get a pin. Since the Oct 26 batch, new records
also carry `week` (the pin week, e.g. `oct-26`), `inflated_original`
and `goods_id` (SHEIN's product id, one per colour). Check a new batch's
goods ids against `products.json` to find repeats. Commit the `product-pin.jpg`
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

## Blog

The blog (`blog/`) is built from `blog-src/` by `py -3 build_blog.py`.
Never edit anything under `blog/` by hand: every page there carries a
"generated by build_blog.py" comment and is rewritten (or removed) on
the next build. `blog-src/` stays off the live site (`_config.yml`
excludes it from GitHub Pages' Jekyll build, which would otherwise
publish each `post.md` as an unstyled page).

**Adding a post.**
1. Make `blog-src/<slug>/` (lowercase, digits, hyphens; the folder name
   is the URL, `blog/<slug>/`; `drafts` is reserved) and put the post's
   photos in it as JPEGs (the originals: the build makes the 500px
   copies).
2. Write `blog-src/<slug>/post.md`: front matter, then the body (see
   the `build_blog.py` docstring for the full syntax).
3. Start with `draft: true`, run `py -3 build_blog.py`, and check the
   page at `blog/drafts/<slug>/` on the local server.
4. To publish, set `draft: false` and set `date` and `updated` to the
   publish date, then run, in order:
   `py -3 build_blog.py` (moves the post to `blog/<slug>/`, removes the
   draft copy, adds it to the listing), `py -3 add_analytics.py`,
   `py -3 add_fonts.py`, `py -3 add_favicons.py` (each should report no
   changes, since the build writes those blocks itself),
   `py -3 write_sitemap.py` (adds the post), and
   `py -3 sync_catalog.py`, which must end clean (item 15 included).
5. Check `blog/<slug>/` and `blog/` on the local server, then commit
   `blog-src/<slug>/`, `blog/` and `sitemap.xml` together.

**Front matter** (between `---` lines): `title`, `description` (the meta
description), `date` and `updated` (YYYY-MM-DD), `category` (label on
the post and listing), `search_phrase` (the one phrase it targets; a
warning if it's in neither title nor description), `hero` (photo
filename; also og:image and twitter:image), `hero_alt`, `draft`
(true/false), `related` (list of site paths for "Explore more", e.g.
`outfits/gameday/`).

**Body.** Markdown subset: `##`/`###` headings, paragraphs, `-` and `1.`
lists, `**bold**`, `*italic*`, links (site pages as `/outfits/gameday/`;
they become relative and must exist), `![alt](photo.jpg "Caption")` on
its own line, and `{{product <products.json id>}}` on its own line for a
product card (name, photo, retailer and affiliate link all come from
`products.json`; consecutive lines make one grid). `{{price <id>}}`
prints a SHEIN price inline. A `## FAQ` section with `###` questions
gets FAQPage JSON-LD. Four or more `##` headings add a table of
contents.

**Prices.** Never type a price. SHEIN prices come from `products.json`
(the card shows it; `{{price <id>}}` inline). Amazon and Awin products
never show one: a price typed in the block before or after an Amazon
card fails the build. Affiliate links in the text get
`rel="nofollow sponsored noopener"` automatically.

**Drafts** build to `blog/drafts/<slug>/` with `noindex`, are linked from
nowhere, and stay out of the sitemap. `blog-src/sample-post/` is a
permanent draft that uses every feature: it's the template's test page,
so keep it a draft.

`build_blog.py --check` reports without changing anything (exit 1 on
anything stale). `sync_catalog.py` report item 15 fails CI on a
published post missing title, description, date or hero; an unknown
`{{product}}` id; a price next to an Amazon card; a missing or stale
-500 JPEG/WebP; a page out of date with its source; a published post
with `noindex` or a draft in the sitemap; and a post without the
affiliate disclosure. The build writes the analytics/consent, footer,
fonts and favicon blocks itself, and `add_analytics.py`,
`add_fonts.py` and `add_favicons.py` keep them current like every
other page.
