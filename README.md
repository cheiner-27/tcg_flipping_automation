# TCG Arbitrage Automation

Finds trading-card arbitrage opportunities by searching eBay for cards listed
**below** their TCGPlayer market value, then hands the results to a separate
review app for human triage. Runs headless in GitHub Actions; the only manual
step is downloading the result CSV and uploading it into the review app.

Supports **Pokémon** and **Magic: The Gathering** (`TCG_CATEGORY`).

---

## Table of contents

1. [The big picture (round-trip)](#the-big-picture-round-trip)
2. [Pipeline stages](#pipeline-stages)
3. [How search terms are built](#how-search-terms-are-built)
4. [Title / content filters](#title--content-filters)
5. [Supabase: what's read vs. written](#supabase-whats-read-vs-written)
6. [The review app (`questioneer-supa-sync`)](#the-review-app-questioneer-supa-sync)
7. [Configuration & secrets](#configuration--secrets)
8. [Running it](#running-it)
9. [Local folders on disk](#local-folders-on-disk)
10. [Gotchas / things future-me will forget](#gotchas--things-future-me-will-forget)

---

## The big picture (round-trip)

```
                 ┌──────────────────────────────────────────────────────────┐
                 │  GitHub Actions (.github/workflows/tcg_arb.yml)            │
                 │  runs src/main.py once/day, alternating game per run #     │
                 └──────────────────────────────────────────────────────────┘
                                          │
   TCGCSV API ──► fetch+build search terms ──► filter (drop sealed / dismissed)
        │                                              │
        │                                              ▼
        │                                   eBay Browse API search
        │                                              │
        ▼                                              ▼
   prices/market value ───────────────► merge + ROI + content filters
                                                       │
                                                       ▼
                                   output/YYYYMMDD_<GAME>_results.csv
                                        (uploaded as GH artifact)
                                                       │
                  ─────────────── MANUAL: download + unzip ───────────────
                                                       │
                                                       ▼
                          Results\YYYYMMDD_<GAME>_results.csv   (local)
                                                       │
                  ─────────────── MANUAL: upload into the app ─────────────
                                                       │
                                                       ▼
           questioneer-supa-sync  (React/Vite app, http://localhost:8080)
            • imports CSV, groups rows by `search_term` into "cards"
            • writes rows → Supabase `arbitrage_results`
            • user dismisses cards/listings → Supabase `dismissed_cards`
              and `dismissed_listings`
                                                       │
                  ◄────────── next pipeline run reads dismissals ──────────
```

The loop closes because **the next pipeline run reads the dismissal tables** and
skips anything the user already rejected. The pipeline never reads
`arbitrage_results` — that table is purely for the app's display.

---

## Pipeline stages

Orchestrated by **`src/main.py:main()`**. Each numbered step prints a header.

| Step | File | What it does |
|------|------|--------------|
| 1. Fetch TCG data | `src/tcgcsv_scraper.py` | Pulls every group/product/price for the category from the free [tcgcsv.com](https://tcgcsv.com) API. **Builds the eBay `searchTerm` here** (see below). Keeps only products whose `marketPrice` is within `[MIN, MAX]`. |
| 2. Fetch dismissals | `src/main.py` (`_fetch_dismissed_cards`, `_fetch_dismissed_listings`) | Reads `dismissed_cards.search_term` and `dismissed_listings.*` from Supabase. |
| 3. Filter TCG list | `src/filter_tcg.py` | Drops sealed/non-single products (name & group exclusion lists), the price-ratio outlier filter, and **removes rows whose `searchTerm` matches a dismissed card** (normalized, fuzzy via exact-normalize). |
| 4. Search eBay | `src/ebay_search.py` | For each surviving `searchTerm`, queries the eBay Browse API (`item_summary/search`). Singles get a category + condition/graded/language aspect filter. Captures `itemEndDate` for the auction-time filter. |
| 5. Merge | `src/transform_results.py` (`merge_with_tcg`) | Joins eBay listings back to TCG data **on the `searchTerm` string**, computes totals and `profit_roi` (buy-on-eBay / sell-on-TCG after fees + shipping). Writes `output/<cat>_results_raw.csv`. |
| 6. Apply filters | `src/transform_results.py` (`apply_filters`) | Title/condition/language/grading filters, ROI threshold, auction-time cutoff, and the **MTG-specific title checks** (collector number, foil, print-variant keywords). Then `_filter_dismissed_listings` removes URL-dismissed listings. |
| 7. Back images | `src/main.py` + `src/image_analysis.py` (`find_best_back`) | For each surviving listing, fetches all eBay item images and scores which extra image is the card back. |
| 8. Download images + save | `src/main.py` | Downloads TCG front / eBay front / back images into `output/images/`, then writes the final **`output/YYYYMMDD_<GAME>_results.csv`** — this is the file you upload to the app. |

`requirements.txt`: `requests`, `beautifulsoup4`, `rapidfuzz`, `supabase` (+ image libs used by `image_analysis`).

---

## How search terms are built

The `searchTerm` is the **single source of truth** for the whole system. The same
string is used to (a) query eBay, (b) join eBay results back to TCG data, (c)
become the `search_term` column in the CSV, (d) get written to `dismissed_cards`
by the app, and (e) get matched against that table on the next run. It is built
**once**, in `src/tcgcsv_scraper.py`.

### Pokémon — `_build_pokemon_search_term`

Strips the set prefix and embedded numbers from the product name, removes
brackets/parens, then formats as `name [num] group [holo|reverse holo]`.
Collector numbers that contain `/` are quoted (`"4/102"`); the title filter then
requires the number to appear in the listing title.

### Magic — `_build_mtg_search_term`

MTG names are messy: qualifiers live in parentheses, and collector numbers are
**alphanumeric** (`410c`) and often **zero-padded in the name** (`(0410c)`) while
the TCGPlayer "Number" field is unpadded (`410c`). The builder does this, in order:

1. **Drop the collector-number parenthetical**, tolerating leading zeros —
   `re.sub(r'\(\s*0*<ext_num>\s*\)', '', name)`. This is why `(0410c)` is removed
   even though `ext_num` is `410c`.
2. **Decide the foil suffix.** From the price subtype: `Foil → " foil"`,
   `Etched → " etched foil"`. **But** if the *name* already contains a foil
   qualifier — detected by the substring **`foil)`** (e.g. `(Silver Scroll Foil)`,
   `(Galaxy Foil)`) — the suffix is skipped so `foil` isn't duplicated. We match
   `foil)` specifically (not bare `foil`) so a card *named* something with "foil"
   isn't a false positive.
3. **Strip all remaining `()[]:` characters but keep the words inside.** So
   `(Borderless)` → `Borderless`, `Secrets of Strixhaven: Mystical Archive` →
   `Secrets of Strixhaven Mystical Archive`. Keeping the words is deliberate — the
   print-variant keyword check (below) needs them in the search term.
4. **Append set / number, de-duping the set name.** If the cleaned set name is
   already a substring of the card name (e.g. `Commander 2015 - Swell the Host`
   with set `Commander 2015`), it is **not** appended again. With a collector
   number: `name num set`. Without one: `name "set"` (set quoted as the
   disambiguator, trimmed by `_clean_set_name`).
5. **Prepend `MTG` to very short terms.** If the finished term is **≤ 3 words**,
   prepend `MTG ` so generic names (`Opt`, `Negate`) don't pull Yu-Gi-Oh!/other
   listings. e.g. `Opt 67 Dominaria` → `MTG Opt 67 Dominaria`.

   > Note: this counts the **whole term**, so once a multi-word set name is
   > appended the term usually exceeds 3 words and is left unprefixed. Change the
   > `len(term.split()) <= 3` check in `_build_mtg_search_term` if you want it to
   > key off the card name instead.

Worked examples (before → after the 2026-06 changes):

| Before (broken) | After |
|---|---|
| `Cavern of Souls (0410c) (Borderless) 410c The Lost Caverns of Ixalan foil` | `Cavern of Souls Borderless 410c The Lost Caverns of Ixalan foil` |
| `Spectacular Spider-Man (0235) (Borderless) (Textured Foil) 235 Marvel's Spider-Man foil` | `Spectacular Spider-Man Borderless Textured Foil 235 Marvel's Spider-Man` |
| `Spell Pierce (JP Alternate Art) (Silver Scroll Foil) 153 Secrets of Strixhaven: Mystical Archive foil` | `Spell Pierce JP Alternate Art Silver Scroll Foil 153 Secrets of Strixhaven Mystical Archive` |
| `Commander 2015 - Swell the Host "Commander 2015"` | `Commander 2015 - Swell the Host` |
| `Opt 67 Dominaria` | `MTG Opt 67 Dominaria` |

Finally, `_quote_special_terms` wraps `prerelease`/`staff`/`promo` in quotes so
eBay treats them as required (applies to both games).

---

## Title / content filters

In `src/transform_results.py` (`apply_filters`). All matched case-insensitively
against the lowercased listing title unless noted.

**Both games:** require a BIN price and `profit_roi >= MIN_ROI`; exclude graded
(`psa/cgc/bgs`), poor condition, damage, non-English language, jumbo/oversized,
quantity lots, and `diy`/`hand drawn` (matched against the search term).

**Magic only:**
- **Set disambiguation (the "R3" rule)** — the hard part, because Magic has many
  reprints/variants of the same card+number across sets. A listing is kept only if:
  1. its title shows **the collector number `_title_has_number` OR a distinctive
     word from the card's set** (`_title_set_signals` → `has_our_set`), **and**
  2. its title does **not** name a *different* set (`names_other_set`).

  Why number-OR-set: Magic sellers omit the bare collector number constantly but
  almost always name the set, so requiring the number alone tanked recall (it was
  the single biggest over-filter — see the funnel discussion). Set words are the
  more reliable signal. The "names a different set" check then catches wrong-print
  false positives the number alone lets through (e.g. a *Grand Prix* promo or
  *Prerelease* card whose number collides with a base-set card, or *Unlimited* vs
  *Beta* old-border cards). On the 2026-06 data this took the disambiguation step
  from 138 → 192 survivors *and* removed real wrong-printing FPs.

  The set model is `build_set_token_model(tcg_data)`, built in `main.py` and passed
  to `apply_filters(set_model=...)` for Magic only (Pokémon passes `None`, which
  falls back to the legacy number-only rule). It keeps only **tokens that uniquely
  identify one set** (a word in 2+ set names is dropped as ambiguous), ignores the
  card's own name tokens (so the card *The Ur-Dragon* isn't read as set
  *Dragon's Maze*), ignores 4-digit years for the other-set signal, and ignores
  colors/grades/filler via `_SET_STOPWORDS`. Caveats: 176/355 sets have no unique
  word (e.g. "Commander 2015") → they fall back to number-only; set abbreviations
  (MH3, LTR) aren't matched yet — a name→code map would recover more.
- `_title_has_number` — the collector number must appear in the title (tolerates
  leading zeros and `#`, e.g. `78` matches `#78`/`078`/`78/264` but not `780`).
  Honors an alphanumeric suffix: ext `410c` matches `410c` or bare `410` but **not**
  `410d`; ext `137` (no suffix) matches `137` but not the variant `137c`.
- `_title_is_foil` — if the subtype is foil, the title must say "foil" (and not
  "non-foil").
- `_title_has_required_keywords` against **`MAGIC_VARIANT_KEYWORDS`** — for each
  of `borderless`, `extended art`, `halo foil`, `foil etched`, `textured foil`,
  `galaxy foil`, `surge foil`: **if it's in the search term, it must be in the
  title.** This is the print-variant equivalent of the foil check. It works
  *because* step 3 of the MTG builder keeps the parenthetical words in the search term.

  > Etched nuance: the builder's *suffix* is `etched foil` (subtype-derived),
  > while the keyword is `foil etched` (the order seen in names like
  > `(Foil Etched)`). They're different strings, so the keyword only enforces when
  > the **name** carried `Foil Etched`. Adjust `MAGIC_VARIANT_KEYWORDS` if you want
  > both orderings enforced.

**Pokémon only:** shadowless, SWSH-suffix, and `XY/SM/BW/DP` prefix-number checks.

---

## Supabase: what's read vs. written

| Table | Pipeline | App |
|-------|----------|-----|
| `dismissed_cards` (`id, search_term, dismissed_at, created_at`) | **reads** `search_term`; rows are removed from the candidate list in step 3 | **writes** — "dismiss card" upserts the card's `search_term` verbatim |
| `dismissed_listings` (`id, listing_url, dismissed_price, dismissal_reason, item_id, created_at`) | **reads**; step 6 removes matching URLs. `reason='condition'` → always drop; `reason='price'` → drop only if current total ≥ `dismissed_price` | **writes** — "dismiss listing" upserts on `listing_url` |
| `arbitrage_results` | not touched | **writes** — clears the table and re-inserts the uploaded CSV (display only) |
| `card_purchases`, `csv_uploads`, `purchases`, `sales`, `inventory`, `saved_listings` | not touched | app-only bookkeeping |

### The consistency invariant (important)

Because the `searchTerm` is built **once** and reused everywhere, within a single
run the string we **search**, the string we **write to the CSV**, and the string
we **match against `dismissed_cards`** are guaranteed identical. There is no way
to "write one thing and look for another" in a given run.

The **cross-run** caveat: changing how `searchTerm` is built (like the 2026-06 MTG
changes above) changes the string. `dismissed_cards` rows written under the *old*
format will no longer match the *new* format, so **previously-dismissed MTG cards
resurface once** and must be re-dismissed in the app. Matching is done via
`filter_tcg._normalize` (strip quotes, collapse whitespace, lowercase) — so quote
and spacing differences are tolerated, but word changes / added `MTG` prefix /
removed parens are not. If a bulk fix is ever needed, `migrate_dismissed_terms.py`
is the template for rewriting existing rows in place.

---

## The review app (`questioneer-supa-sync`)

Lives at `C:\Users\chrsh\Documents\01. Programming\06. TCG Arb\questioneer-supa-sync`
(sibling folder). React + Vite + Supabase. Main component:
`src/components/arbitrage/ArbitrageAnalysis.tsx`.

**Run it:**
```
cd "C:\Users\chrsh\Documents\01. Programming\06. TCG Arb\questioneer-supa-sync"
npm install      # first time
npm run dev      # → http://localhost:8080
```
Needs `.env` with `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY`,
`VITE_SUPABASE_PROJECT_ID` (already present in the repo). `vite.config.ts` also
serves local card images from `../Results/images` at `/local-images/`.

**What it does with the CSV:**
1. Parses the CSV (PapaParse). Expected columns match `_merged_fields()` in
   `src/main.py` — `search_term, item_id, title, …, buy_it_now_total, ROI,
   profit_roi, tcglist_<cat>.*, *_image_*`.
2. **Groups rows by `search_term` into "cards".** One card = one TCGPlayer product
   + every eBay listing that shared that search term. This is why the pipeline's
   "N opportunities" (one row per listing) shows as far fewer *cards* in the app
   (e.g. 1218 listings → 185 cards).
3. Clears and re-inserts `arbitrage_results` with the uploaded rows.

**Dismissals (what feeds back to the pipeline):**
- *Dismiss a card* → upsert into `dismissed_cards` with `search_term` (trimmed,
  verbatim). The whole card disappears and the pipeline skips it next run.
- *Dismiss a listing* → upsert into `dismissed_listings` keyed on `listing_url`,
  with `dismissal_reason` `'condition'` (permanent) or `'price'` (snooze; stores
  the current price and reappears only if it drops below that).

Supabase schema/migrations live in `questioneer-supa-sync/supabase/migrations/*.sql`.

---

## Configuration & secrets

All config is env vars (`src/config.py`), set in the workflow YAML `env:` block:

| Var | Default | Notes |
|-----|---------|-------|
| `TCG_CATEGORY` | `pokemon` | `pokemon` or `magic`; CI auto-alternates by run number |
| `POKEMON_MIN_PRICE` / `MAX` | `15` / `2000` | CI uses `30` / `3000` |
| `MAGIC_MIN_PRICE` / `MAX` | `35` / `1000` | filters on TCGPlayer `marketPrice` |
| `MIN_ROI` | `0.07` | CI uses `0.05`; min `profit_roi` to keep a listing |
| `MAX_AUCTION_DAYS` | `2` | drop auctions ending later than this |
| `BUYER_COUNTRY` / `BUYER_ZIP` | `US` / `21015` | for eBay delivery/shipping calc |
| `EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET` | — | eBay OAuth (client_credentials) |
| `SUPABASE_URL` / `SUPABASE_KEY` | — | dismissals DB |
| `SUPABASE_DISMISSED_TABLE` | `dismissed_cards` | |
| `SUPABASE_DISMISSED_LISTINGS_TABLE` | `dismissed_listings` | |

Secrets (`EBAY_*`, `SUPABASE_*`) live in **GitHub repo secrets**, not in code.

---

## Running it

**In CI (normal):** `.github/workflows/tcg_arb.yml` runs daily at 23:00 UTC.
**Even** run numbers → Magic, **odd** → Pokémon. `workflow_dispatch` lets you
force a `category`. Results upload as artifact `tcg-results-<cat>-<run#>`
(`output/` folder, 30-day retention). Download + unzip into `Results\`.

**Locally:**
```
pip install -r requirements.txt
# set the env vars from the table above (at minimum EBAY_* ; SUPABASE_* optional)
python src/main.py
```
Output lands in `output/` (CSVs + `images/`). Without Supabase creds the dismissal
steps are skipped (it prints "Supabase credentials not set").

---

## Local folders on disk

Under `C:\Users\chrsh\Documents\01. Programming\06. TCG Arb\`:

- `tcg_flipping_automation\` — **this** Python pipeline.
- `Results\` — downloaded GH artifact CSVs, named `YYYYMMDD_<GAME>_results.csv`
  (e.g. `20260612_MAGIC_results.csv`), plus an `images\` subfolder.
- `questioneer-supa-sync\` — the React review app.
- `Current Workflow\` — original scripts kept for reference (not used).

---

## Gotchas / things future-me will forget

- **`searchTerm` is sacred.** It's built once in `tcgcsv_scraper.py` and reused as
  the join key, the eBay query, the CSV column, and the dismissal key. Change its
  format and old `dismissed_cards` rows stop matching (see the consistency section).
- **The pipeline only reads `dismissed_cards` / `dismissed_listings`.** It never
  reads `arbitrage_results`; that's display-only for the app.
- **MTG numbers are alphanumeric and zero-padded in names.** `(0410c)` vs `410c`.
  The leading-zero-tolerant regex in step 1 of the MTG builder is what fixes this.
- **Keeping parenthetical words is intentional** — the `MAGIC_VARIANT_KEYWORDS`
  title check depends on `Borderless`/`Textured Foil`/etc. staying in the term.
- **Magic match precision lives in the "R3" set rule**, not the collector number —
  see the Title/content filters section. Number-OR-set + not-other-set; the set
  model is built in `main.py` from the *full* `tcg_data` (so it knows every set
  name) and passed to `apply_filters`. Pokémon passes `None` and is unaffected.
- **`foil)` (not bare `foil`)** is the signal that a foil qualifier is already in
  the name, so we don't double-append `foil`.
- **The CSV → app upload is manual.** Nothing automatically pushes the artifact
  into Supabase; you upload it in the app, which then writes `arbitrage_results`.
- No automated tests exist. Quick sanity check after editing the builders:
  `python -c "import sys; sys.path.insert(0,'src'); from tcgcsv_scraper import _build_mtg_search_term as b; print(b('Opt','67','Dominaria','Normal'))"`
