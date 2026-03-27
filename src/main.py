import csv
import os
import sys

# Ensure the src/ directory is on the path so sibling modules resolve correctly
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from tcgcsv_scraper import fetch_tcg_data
from filter_tcg import filter_tcg_data
from ebay_search import search_all_terms
from transform_results import merge_with_tcg, apply_filters

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'output')

TCG_FIELDS = [
    'productId', 'group', 'name', 'ext_num', 'cleanName',
    'searchTerm', 'url', 'subTypeName', 'lowPrice', 'midPrice', 'marketPrice',
]


def _merged_fields(category: str) -> list:
    """Column order matching the old PowerQuery output format."""
    p = f'tcglist_{category}'
    return [
        'search_term', 'item_id', 'title', 'auction_price', 'buy_it_now_price',
        'shipping_cost', 'url',
        f'{p}.productId', f'{p}.searchTerm', f'{p}.url', f'{p}.subTypeName',
        f'{p}.lowPrice', f'{p}.midPrice', f'{p}.marketPrice',
        'Total Time', 'buy_it_now_total', 'auction_total', 'ROI',
    ]


def _save_csv(data: list, filepath: str, fieldnames: list) -> None:
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(data)
    print(f"  Saved {len(data)} rows → {os.path.basename(filepath)}")


def _fetch_dismissed_cards() -> list:
    if not config.SUPABASE_URL or not config.SUPABASE_KEY:
        print("  Supabase credentials not set — skipping dismissed cards.")
        return []

    from supabase import create_client
    client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)

    all_rows = []
    page_size = 1000
    offset = 0
    while True:
        response = (
            client.table(config.SUPABASE_DISMISSED_TABLE)
            .select('search_term')
            .range(offset, offset + page_size - 1)
            .execute()
        )
        rows = response.data or []
        all_rows.extend(rows)
        if len(rows) < page_size:
            break
        offset += page_size

    terms = [r['search_term'] for r in all_rows if r.get('search_term')]
    print(f"  Fetched {len(terms)} dismissed cards from Supabase")
    return terms


def main():
    from datetime import datetime
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    cat = config.TCG_CATEGORY
    date_str = datetime.now().strftime('%Y%m%d')
    merged_fields = _merged_fields(cat)

    print('=== Step 1: Fetch TCG data ===')
    tcg_data = fetch_tcg_data(cat, min_price=config.TCG_MIN_PRICE, max_price=config.TCG_MAX_PRICE)
    _save_csv(tcg_data, os.path.join(OUTPUT_DIR, f'tcglist_{cat}.csv'), TCG_FIELDS)

    print('\n=== Step 2: Fetch dismissed cards from Supabase ===')
    dismissed = _fetch_dismissed_cards()

    print('\n=== Step 3: Filter TCG list ===')
    filtered = filter_tcg_data(tcg_data, dismissed)
    _save_csv(filtered, os.path.join(OUTPUT_DIR, f'tcglist_{cat}_filtered.csv'), TCG_FIELDS)

    print('\n=== Step 4: Search eBay ===')
    search_terms = [row['searchTerm'] for row in filtered]
    ebay_raw = search_all_terms(search_terms)

    print('\n=== Step 5: Merge with TCG data ===')
    merged = merge_with_tcg(ebay_raw, tcg_data, cat)
    # This file matches the old PowerQuery format — upload this to your tool
    _save_csv(merged, os.path.join(OUTPUT_DIR, f'{cat}_results_raw.csv'), merged_fields)

    print('\n=== Step 6: Apply filters ===')
    final = apply_filters(merged)
    _save_csv(final, os.path.join(OUTPUT_DIR, f'{date_str}_{cat.upper()}_results.csv'), merged_fields)

    print(f'\nDone. {len(final)} opportunities in final results ({len(merged)} pre-filter).')


if __name__ == '__main__':
    main()
