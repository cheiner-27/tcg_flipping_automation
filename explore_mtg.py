"""
Exploratory pull of MTG singles from TCGCSV.
Applies a series of filters and reports counts at each stage.
Saves the final filtered set to explore_mtg_output.csv.
"""

import csv
import sys
import time
import requests

CATEGORY_ID = '1'  # Magic: The Gathering
HEADERS = {"User-Agent": "TCGFlippingAutomation/1.0.0"}
MIN_PRICE = 35
MAX_PRICE = 1000
MID_RATIO_MIN = 0.5   # market/mid must be >= this

# ── Sealed-product name substrings ───────────────────────────────────────────
# Ordered roughly most-to-least specific so the first match wins on a substring
SEALED_NAME_TERMS = [
    'Booster',        # Draft/Set/Collector/Jumpstart/etc. boosters
    'Bundle',         # "Bundle" product type
    'Commander Deck', # precon commander decks
    'Starter Kit',
    'Starter Deck',
    'Starter Set',
    'Theme Deck',
    'Fat Pack',
    'Gift Pack',
    'Gift Set',
    'Prerelease Pack',  # "Prerelease" alone is fine (promo singles); "Pack" is the product
    'Promo Pack',
    'Tournament Pack',
    'Intro Pack',
    'Event Deck',
    'Deck Box',         # storage accessory
    'Deckbox',
    'Playmat',
    'Sleeves',
    'Binder',
    'Dice',
    'Display',          # "Booster Display" / "Set Display"
    'Case',             # booster case
    'Sealed',
    'Box Set',
    'Box Topper',       # individual box toppers are singles; "Box Topper Set" is not
    'Oversized',        # oversized promo/display cards
    'Life Counter',
    'Spindown',
    ' Deck'             # "Deck" alone is fine (promo singles); " Deck" is the product
]

# ── Token / non-singles name substrings ──────────────────────────────────────
TOKEN_TERMS = [
    ' Token',    # " Token" with leading space to avoid clipping e.g. "Tokenize"
    'Emblem',    # emblems placed on the battlefield — not real singles
    'Checklist', # double-faced card checklist placeholders
    'Art Card',  # Secret Lair art series insert cards
    'Punch Card', # punch-out counters/tokens
]

# ── Group-level exclusions ────────────────────────────────────────────────────
# These MTG-specific group types produce no tradeable singles
GROUP_EXCLUDE_CONTAINS = [
    'Jumbo',         # oversized promos
    'Oversize',
    'Championship',  # store-championship non-single items
]


def _get(url):
    r = requests.get(url, headers=HEADERS)
    r.raise_for_status()
    time.sleep(0.1)
    return r.json()


def fetch_raw():
    print("Fetching all MTG groups…")
    groups = _get(f"https://tcgcsv.com/tcgplayer/{CATEGORY_ID}/groups")['results']
    print(f"  {len(groups)} groups found")

    rows = []
    for i, group in enumerate(groups, 1):
        gid = group['groupId']
        gname = group['name']
        if i % 50 == 0:
            print(f"  …processed {i}/{len(groups)} groups ({len(rows)} rows so far)")

        products = _get(f"https://tcgcsv.com/tcgplayer/{CATEGORY_ID}/{gid}/products")['results']
        prices_raw = _get(f"https://tcgcsv.com/tcgplayer/{CATEGORY_ID}/{gid}/prices")['results']
        price_map = {p['productId']: p for p in prices_raw}

        for product in products:
            pid = product['productId']
            price = price_map.get(pid, {})
            rows.append({
                'productId':   pid,
                'group':       gname,
                'name':        product['name'],
                'cleanName':   product['cleanName'],
                'url':         product.get('url', ''),
                'subTypeName': price.get('subTypeName', 'N/A'),
                'lowPrice':    price.get('lowPrice'),
                'midPrice':    price.get('midPrice'),
                'marketPrice': price.get('marketPrice'),
            })

    print(f"Raw fetch complete: {len(rows)} total product×price rows\n")
    return rows


def _f(val):
    """Safe float conversion — returns None on failure."""
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def apply_filters(rows):
    stages = [("Raw fetch", rows)]

    # 1. Price range
    def in_price_range(r):
        mp = _f(r['marketPrice'])
        return mp is not None and MIN_PRICE <= mp <= MAX_PRICE

    after_price = [r for r in rows if in_price_range(r)]
    stages.append((f"Market price ${MIN_PRICE}–${MAX_PRICE}", after_price))

    # 2. Sealed products (name-based)
    def is_single(r):
        lower = r['name'].lower()
        return not any(t.lower() in lower for t in SEALED_NAME_TERMS)

    after_sealed = [r for r in after_price if is_single(r)]
    stages.append(("Remove sealed / accessories", after_sealed))

    # 3. Tokens, emblems, checklist cards, art cards
    def not_token(r):
        lower = r['name'].lower()
        return not any(t.lower() in lower for t in TOKEN_TERMS)

    after_tokens = [r for r in after_sealed if not_token(r)]
    stages.append(("Remove tokens / emblems / art cards", after_tokens))

    # 4. Group-level exclusions
    def group_ok(r):
        lower = r['group'].lower()
        return not any(t.lower() in lower for t in GROUP_EXCLUDE_CONTAINS)

    after_groups = [r for r in after_tokens if group_ok(r)]
    stages.append(("Exclude non-singles group types", after_groups))

    # 5. market/mid ratio — must be >= 0.5 to suggest reasonable volume
    def mid_ratio_ok(r):
        mp = _f(r['marketPrice'])
        mid = _f(r['midPrice'])
        if mp is None or mid is None or mid <= 0:
            return False  # drop if we can't compute — no usable price data
        return (mp / mid) >= MID_RATIO_MIN

    after_ratio = [r for r in after_groups if mid_ratio_ok(r)]
    stages.append((f"market/mid ratio >= {MID_RATIO_MIN}", after_ratio))

    # 6. Must have a valid low price (basic sanity — no data = skip)
    after_low = [r for r in after_ratio if _f(r['lowPrice']) is not None]
    stages.append(("Has a valid low price", after_low))

    return stages


def print_report(stages):
    print("=" * 60)
    print("FILTER FUNNEL")
    print("=" * 60)
    for label, data in stages:
        print(f"  {len(data):>7,}  {label}")
    print()

    final = stages[-1][1]
    if not final:
        print("No cards passed all filters.")
        return

    # subtype breakdown
    from collections import Counter
    subtypes = Counter(r['subTypeName'] for r in final)
    print("Subtype breakdown:")
    for sub, cnt in subtypes.most_common():
        print(f"  {sub:<30} {cnt:>6,}")
    print()

    # top 20 groups by count
    groups = Counter(r['group'] for r in final)
    print("Top 20 groups by card count:")
    for grp, cnt in groups.most_common(20):
        print(f"  {grp:<50} {cnt:>5,}")
    print()

    # price distribution buckets
    buckets = {
        '$35–$49':   0, '$50–$74':   0, '$75–$99':  0,
        '$100–$199': 0, '$200–$499': 0, '$500–$1000': 0,
    }
    for r in final:
        mp = float(r['marketPrice'])
        if mp < 50:    buckets['$35–$49'] += 1
        elif mp < 75:  buckets['$50–$74'] += 1
        elif mp < 100: buckets['$75–$99'] += 1
        elif mp < 200: buckets['$100–$199'] += 1
        elif mp < 500: buckets['$200–$499'] += 1
        else:          buckets['$500–$1000'] += 1
    print("Price distribution:")
    for bucket, cnt in buckets.items():
        print(f"  {bucket:<15} {cnt:>6,}")
    print()


def save_csv(rows, path='explore_mtg_output.csv'):
    if not rows:
        return
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"Saved {len(rows):,} rows → {path}")


if __name__ == '__main__':
    raw = fetch_raw()
    stages = apply_filters(raw)
    print_report(stages)
    save_csv(stages[-1][1])
