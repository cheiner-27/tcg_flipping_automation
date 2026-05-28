import csv
import os
import sys
import time
from urllib.parse import urlparse

import requests

# Ensure the src/ directory is on the path so sibling modules resolve correctly
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from tcgcsv_scraper import fetch_tcg_data
from filter_tcg import filter_tcg_data
from ebay_search import search_all_terms, get_oauth_token, fetch_item_images
from transform_results import merge_with_tcg, apply_filters
from image_analysis import find_best_back

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
        'profit_roi', 'ebay_image_url', 'tcg_image_url',
        'back_image_url', 'back_image_score',
        'tcg_image_local', 'ebay_front_image_local', 'back_image_local',
    ]


def _save_csv(data: list, filepath: str, fieldnames: list) -> None:
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(data)
    print(f"  Saved {len(data)} rows → {os.path.basename(filepath)}")


def _normalize_url(url: str) -> str:
    """Strip query params/fragment for stable URL matching across runs."""
    try:
        p = urlparse(url.strip())
        return f"{p.scheme}://{p.netloc}{p.path}"
    except Exception:
        return url.strip().split('?')[0].split('#')[0]


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


def _fetch_dismissed_listings() -> list:
    if not config.SUPABASE_URL or not config.SUPABASE_KEY:
        print("  Supabase credentials not set — skipping dismissed listings.")
        return []

    from supabase import create_client
    client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)

    all_rows = []
    page_size = 1000
    offset = 0
    while True:
        response = (
            client.table(config.SUPABASE_DISMISSED_LISTINGS_TABLE)
            .select('listing_url,dismissed_price,dismissal_reason')
            .range(offset, offset + page_size - 1)
            .execute()
        )
        rows = response.data or []
        all_rows.extend(rows)
        if len(rows) < page_size:
            break
        offset += page_size

    print(f"  Fetched {len(all_rows)} dismissed listings from Supabase")
    return all_rows


def _filter_dismissed_listings(results: list, dismissed: list) -> list:
    """
    Remove results that match a dismissed listing entry.

    dismissal_reason='condition' → always excluded.
    dismissal_reason='price'     → excluded only if current buy_it_now_total
                                   is still >= the dismissed_price (i.e. not
                                   dropped enough to be interesting again).
    """
    if not dismissed:
        return results

    url_map: dict[str, dict] = {}
    for row in dismissed:
        url_key = _normalize_url(row.get('listing_url') or '')
        if url_key:
            url_map[url_key] = {
                'price': row.get('dismissed_price'),
                'reason': row.get('dismissal_reason') or 'condition',
            }

    output = []
    skipped = 0
    for row in results:
        url_key = _normalize_url(row.get('url', ''))
        dismissal = url_map.get(url_key)
        if dismissal:
            reason = dismissal['reason']
            if reason == 'condition':
                skipped += 1
                continue
            if reason == 'price':
                current = row.get('buy_it_now_total') or 0
                threshold = dismissal['price']
                if threshold is not None and current >= threshold:
                    skipped += 1
                    continue
        output.append(row)

    print(f"  Skipped {skipped} dismissed listings → {len(output)} remain")
    return output


def _url_ext(url: str) -> str:
    ext = os.path.splitext(urlparse(url).path)[1].lower()
    return ext if ext in ('.jpg', '.jpeg', '.png', '.webp') else '.jpg'


def _download_file(session: requests.Session, url: str, filepath: str) -> bool:
    if os.path.exists(filepath):
        return True
    try:
        r = session.get(url, timeout=15)
        r.raise_for_status()
        with open(filepath, 'wb') as f:
            f.write(r.content)
        return True
    except Exception:
        return False


def _download_images(results: list, images_dir: str, category: str) -> None:
    os.makedirs(images_dir, exist_ok=True)
    prefix = f'tcglist_{category}'
    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0'})

    # TCG front images — deduped by productId (many listings share the same card)
    tcg_cache: dict[str, str] = {}
    for row in results:
        product_id = str(row.get(f'{prefix}.productId') or '').strip()
        if product_id in tcg_cache:
            row['tcg_image_local'] = tcg_cache[product_id]
            continue
        tcg_url = row.get('tcg_image_url', '')
        if not tcg_url or not product_id:
            row['tcg_image_local'] = ''
            tcg_cache[product_id] = ''
            continue
        filename = f'tcg_{product_id}{_url_ext(tcg_url)}'
        local = f'images/{filename}' if _download_file(session, tcg_url, os.path.join(images_dir, filename)) else ''
        tcg_cache[product_id] = local
        row['tcg_image_local'] = local

    # eBay front + back images — one pair per listing
    front_count = back_count = 0
    for row in results:
        safe_id = row.get('item_id', 'unknown').replace('|', '_')

        front_url = row.get('ebay_image_url', '')
        if front_url:
            filename = f'front_{safe_id}{_url_ext(front_url)}'
            local = f'images/{filename}' if _download_file(session, front_url, os.path.join(images_dir, filename)) else ''
            row['ebay_front_image_local'] = local
            if local:
                front_count += 1
        else:
            row['ebay_front_image_local'] = ''

        back_url = row.get('back_image_url', '')
        if back_url:
            filename = f'back_{safe_id}{_url_ext(back_url)}'
            local = f'images/{filename}' if _download_file(session, back_url, os.path.join(images_dir, filename)) else ''
            row['back_image_local'] = local
            if local:
                back_count += 1
        else:
            row['back_image_local'] = ''

    print(f"  {len(tcg_cache)} TCG fronts, {front_count} eBay fronts, {back_count} backs downloaded → images/")


def main():
    from datetime import datetime
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    cat = config.TCG_CATEGORY
    date_str = datetime.now().strftime('%Y%m%d')
    merged_fields = _merged_fields(cat)

    print('=== Step 1: Fetch TCG data ===')
    tcg_data = fetch_tcg_data(cat, min_price=config.TCG_MIN_PRICE, max_price=config.TCG_MAX_PRICE)
    _save_csv(tcg_data, os.path.join(OUTPUT_DIR, f'tcglist_{cat}.csv'), TCG_FIELDS)

    print('\n=== Step 2: Fetch dismissed data from Supabase ===')
    dismissed = _fetch_dismissed_cards()
    dismissed_listings = _fetch_dismissed_listings()

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
    final = _filter_dismissed_listings(final, dismissed_listings)

    print(f'\n=== Step 7: Fetch back images for {len(final)} profitable results ===')
    token = get_oauth_token()
    found = 0
    for i, row in enumerate(final, 1):
        item_id = row.get('item_id', '')
        if not item_id:
            row['back_image_url'] = ''
            row['back_image_score'] = -1
            continue

        # Fetch all listing images; first one from item detail is the seller's primary (front)
        detail_urls = fetch_item_images(item_id, token)
        row['ebay_image_url'] = detail_urls[0] if detail_urls else ''

        back_url, back_score = find_best_back(detail_urls)
        row['back_image_url']   = back_url or ''
        row['back_image_score'] = back_score
        if back_url:
            found += 1

        if i % 25 == 0 or i == len(final):
            print(f"  [{i}/{len(final)}] backs found so far: {found}")
        time.sleep(0.25)

    print(f'\n=== Step 8: Download images ===')
    _download_images(final, os.path.join(OUTPUT_DIR, 'images'), cat)

    _save_csv(final, os.path.join(OUTPUT_DIR, f'{date_str}_{cat.upper()}_results.csv'), merged_fields)

    print(f'\nDone. {len(final)} opportunities, {found} with a back image identified.')


if __name__ == '__main__':
    main()
