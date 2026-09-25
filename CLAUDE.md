# CLAUDE.md

Guidance for Claude Code (and other agents) working in this repo.

## Repo root redirect stubs

The repo root contains ~70 folders whose names look like campaign slugs
(e.g. `casual-august1/`, `business-casual-aug-10/`, `eagles-broncos/`)
but sit outside both `outfits/` and `videos/`. **These are intentional
redirect stubs that keep pre-restructure Pinterest links working** —
they are not build leftovers, orphaned artifacts, or duplicates to clean
up. Do not delete, move, or modify them, in this task or in any later
cleanup pass, without explicit instruction to do so.

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
`sync_catalog.py`'s report item 6 flags any page whose block is missing
or stale, and any detail page with no outbound `.shop` link.

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

So the order is: `sync_catalog.py` (plus `--append` if needed), then
`add_product_schema.py`, then `add_analytics.py`, then
`write_sitemap.py` last among the writers (both scripts before it edit
pages, and each edit moves that page's `<lastmod>`), then
`sync_catalog.py` once more to confirm it's clean.
