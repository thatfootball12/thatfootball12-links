# ThatFootball12 Pin Copy Guide

These are Jesse's standing rules for writing Pinterest pin copy. Follow them for every pin, then have Jesse spot-check a sample before uploading.

## Audience and voice
- Write like a marketer who's good at turning readers into buyers. The audience is men aged 22–30.
- Each product link gets its own pin.
- Every title and description must be unique, even for the same product.
- Keep the tone warm, genuine and conversational, like a real person recommending something to a friend. Never salesy or robotic.
- Urgency should feel natural. Never pushy or made up.

## Length (Pinterest limits)
- **Title:** short and punchy, well under 100 characters, with 1–2 emojis where natural.
- **Description:** Pinterest caps it at **500 characters**, and that includes the disclosure, the AI line and the hashtags. Keep the copy itself to **about 250–290 characters**: 2–3 short sentences using 2–3 keywords from the bank.
- In `make_pinterest_csv.py` input (`pins_<date>.json`), the description field holds **copy only**. The script adds the disclosure and the hashtags.

## Product pins
- **Title:** use ONE value angle:
  - **Price anchor:** "$18", "Under $20"
  - **Discount math:** "$60 Outfit, $22 Total"
  - **Scarcity or urgency**, only if it's true
  - **Social proof plus value**
  - **Convenience:** "Zero Guesswork", "One Tap Outfit", "Stop Overthinking This"
- **Title examples:** "$45 Look for $17: Full Breakdown Inside" / "The $19 Piece Beating Out $40+ Alternatives Right Now" / "One Outfit, Zero Guesswork — [Product] Alert"
- **Price:**
  - Never invent a price or an original price.
  - If a price is missing or uncertain, write "PRICE NOT FOUND — insert manually" as a separate flagged line, never inside the description.
  - Amazon pins: never state a price. Write "Check price on Amazon" or leave price out.
- **Description:**
  - In the first 1–2 sentences, state the price or value angle plainly, together with one quality, fit or true-to-size signal. Example: "$34 utility jacket — true to size, holds up in cold".
  - If several discounts stack (site sale + coupon + new-user offer), name each one.
  - Add a short occasion tag where it fits: Gameday-ready, Office-appropriate, Everyday.
  - **Last sentence:** genuine urgency (deal timing, social proof, trend). Use stock or restock claims ONLY if they're confirmed.
- **Hashtags:** 4 from the keyword bank. Include at least one buy-intent tag (#Under20Finds, #DealAlert, #ShopThisLook), and favour occasion and intent tags over broad ones.
- **Alt text:** one per pin, under 100 characters, SEO-friendly. Describe the product and who it's for, without repeating the title.

## Outfit pins
- **Title:** leads with style, identity or aspiration. NO prices or deal language.
- **Title examples:** "Old Money Fit Nobody's Talking About Yet" / "Game Day Fit That Doesn't Look Like a Jersey" / "The Fit That Says "I Have My Life Together""
- **Description:**
  - 2–3 conversational sentences about the look, feel and occasion. No price, discount or deal framing.
  - Add a versatility line where it fits: "already own the jeans? just add this".
  - Gameday and fan outfits: add a line that takes away the risk of looking silly, e.g. "fan gear that still looks like an outfit, not a costume".
  - **Last sentence:** trend timing, seasonal relevance or social proof. No scarcity or restock language.
- Same disclosure and 4 bank hashtags as product pins.

## Disclosure (exact wording, at the end of the description)
- **SHEIN only:** "As a SHEIN Affiliate, I earn from qualifying purchases. Prices may change."
- **Any Amazon item:** "As a SHEIN Affiliate and Amazon Associate, I earn from qualifying purchases. Prices may change."
- **AI image** (all outfit pins and Amazon pins): also add "Image created with AI." In Pinterest, also tick "Mark as AI-modified", plus "includes an AI-generated person" when a person appears.

## Boards
- Give every pin a board and a section from `pinterest/pin_settings.json`. Section names can't contain "/".
- **Theme routing:**
  - **Gameday** → Game Day Outfits for Men
  - **Casual** → Fall Casual Outfits for Men
  - **Streetwear and Motor Streetwear** → Men's Fall Streetwear 2026
  - **Old Money** → Business Casual Outfits for Men
  - **Date Night / Night Out** → Business Casual Outfits for Men › Date Night & Night Out
  - **Wedding and Formal** → Life Events & Special Occasions Outfits for Men
  - **Fall product pins** → Men's Fall Style Essentials
  - **Holiday gift pins** → Christmas Gifts for Men 2026: Gameday Gifts, Splurge $100+, $60–$100, $25–$60, Under $25
- When a pin fits both a category section and a price-tier section, mix them: put some in each.

## Keyword bank (pick naturally, no stuffing)
- **Men's fashion:** men's fall outfits, mens fall fashion, fall outfit ideas men, autumn style men, mens casual outfits, street style men, layered fall outfits men, mens fall sweaters, chunky knitwear men, flannel shirt outfits men, shacket outfits men, chore coat outfits men, corduroy outfits men, mens fall boots, mens fall jackets, loafers fall outfits men, dapper mens outfits, male preppy outfits, rugged luxury men, heritage workwear outfits men, casual autumn style men, mens fall street style, chocolate brown outfits men
- **Fashion hashtags:** #mensfallfashion #mensfashion #fallfashion #menswear #mensstyle #autumnstyle #mensoutfits #falloutfitsmen #streetstylemen #preppystyle
- **Football × fashion:** game day outfit men casual, game day streetwear, NFL streetwear outfit men, football fan style men, Sunday fit football fan, stadium streetwear, tailgate outfit men, team color outfit men casual, athleisure football fan style
