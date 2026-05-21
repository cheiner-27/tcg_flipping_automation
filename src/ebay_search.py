import base64
import time
import requests
from datetime import datetime, timezone
from urllib.parse import quote

import config

_OAUTH_TOKEN_CACHE = None


def _get_oauth_token() -> str:
    global _OAUTH_TOKEN_CACHE
    if _OAUTH_TOKEN_CACHE:
        return _OAUTH_TOKEN_CACHE

    credentials = f'{config.EBAY_CLIENT_ID}:{config.EBAY_CLIENT_SECRET}'
    encoded = base64.b64encode(credentials.encode()).decode()
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Authorization': f'Basic {encoded}',
    }
    data = {
        'grant_type': 'client_credentials',
        'scope': 'https://api.ebay.com/oauth/api_scope',
    }
    r = requests.post('https://api.ebay.com/identity/v1/oauth2/token', headers=headers, data=data)
    if r.status_code != 200:
        raise RuntimeError(f"eBay OAuth error {r.status_code}: {r.text}")

    _OAUTH_TOKEN_CACHE = r.json()['access_token']
    return _OAUTH_TOKEN_CACHE


def _enduserctx() -> str:
    return f"contextualLocation={quote(f'country={config.BUYER_COUNTRY},zip={config.BUYER_ZIP}', safe='')}"


def _is_singles_term(term: str) -> bool:
    t = term.lower()
    if any(kw in t for kw in ('unopened', 'booster', 'box', 'case', 'deck', 'sealed')):
        return False
    if 'pack' in t and '"' not in term:
        return False
    return True


def _best_shipping(shipping_options) -> float | None:
    best = None
    for opt in shipping_options or []:
        if (opt.get('type') or '').upper() == 'PICKUP':
            continue
        sc = opt.get('shippingCost')
        if sc and sc.get('value') is not None:
            try:
                v = float(sc['value'])
                best = v if best is None else min(best, v)
            except (TypeError, ValueError):
                pass
    return best


def _search_term_results(search_term: str, token: str) -> list:
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
        'X-EBAY-C-MARKETPLACE-ID': 'EBAY_US',
        'X-EBAY-C-ENDUSERCTX': _enduserctx(),
    }

    singles = _is_singles_term(search_term)
    base_filter = (
        f'buyingOptions:{{AUCTION|FIXED_PRICE}},'
        f'deliveryCountry:{config.BUYER_COUNTRY},'
        f'deliveryPostalCode:{config.BUYER_ZIP}'
    )

    params = {
        'q': search_term,
        'fieldgroups': 'EXTENDED,ASPECT_REFINEMENTS',
        'filter': base_filter,
    }
    if singles:
        params['category_ids'] = '183454'
        params['aspect_filter'] = (
            'categoryId:183454,'
            'Card Condition:{Near Mint or Better},'
            'Graded:{No},'
            'Language:{English}'
        )

    results = []
    offset = 0
    limit = 200
    now = datetime.now(timezone.utc)

    while True:
        params['limit'] = str(limit)
        params['offset'] = str(offset)

        for attempt in range(4):
            try:
                r = requests.get(
                    'https://api.ebay.com/buy/browse/v1/item_summary/search',
                    headers=headers,
                    params=params,
                    timeout=30,
                )
                break
            except requests.exceptions.ConnectionError as e:
                if attempt == 3:
                    raise
                wait = 2 ** attempt * 5
                print(f"  Connection error for '{search_term}', retrying in {wait}s: {e}")
                time.sleep(wait)
        if r.status_code == 429:
            retry_after = int(r.headers.get('Retry-After', 60))
            print(f"  Rate limited; sleeping {retry_after}s")
            time.sleep(retry_after)
            continue
        if r.status_code != 200:
            print(f"  eBay error for '{search_term}': {r.status_code}")
            break

        data = r.json()
        items = data.get('itemSummaries') or []
        if not items:
            break

        for item in items:
            buying_options = item.get('buyingOptions') or []
            price_info = item.get('price') or {}
            price = price_info.get('value')
            bid_info = item.get('currentBidPrice') or {}
            bidprice = bid_info.get('value')

            auction_price = buy_it_now_price = None
            if 'AUCTION' in buying_options:
                auction_price = bidprice or price
                if 'FIXED_PRICE' in buying_options:
                    buy_it_now_price = price
            elif 'FIXED_PRICE' in buying_options:
                buy_it_now_price = price

            # Compute seconds until listing ends (auctions have itemEndDate)
            time_remaining_seconds = None
            end_date = item.get('itemEndDate')
            if end_date:
                try:
                    end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                    delta = end_dt - now
                    time_remaining_seconds = max(delta.total_seconds(), 0)
                except Exception:
                    pass

            card_condition = ''
            for d in item.get('conditionDescriptors') or []:
                if (d.get('name') or '').strip().lower() == 'card condition':
                    vs = d.get('values') or []
                    if vs:
                        card_condition = vs[0].get('content', '') or ''
                    break

            results.append({
                'search_term': search_term,
                'item_id': item.get('itemId', ''),
                'title': item.get('title', ''),
                'auction_price': auction_price,
                'buy_it_now_price': buy_it_now_price,
                'shipping_cost': _best_shipping(item.get('shippingOptions')),
                'currency': price_info.get('currency', ''),
                'time_remaining_seconds': time_remaining_seconds,
                'url': item.get('itemWebUrl', ''),
                'card_condition': card_condition,
            })

        if 'next' not in data:
            break
        offset += limit
        if offset >= 10000:
            print(f"  Hit 10k item limit for '{search_term}'")
            break

    return results


def search_all_terms(search_terms: list) -> list:
    print("Obtaining eBay OAuth token...")
    token = _get_oauth_token()
    total = len(search_terms)
    all_results = []

    for i, term in enumerate(search_terms, 1):
        print(f"  [{i}/{total}] {term}")
        all_results.extend(_search_term_results(term, token))
        time.sleep(0.25)

    print(f"eBay search complete: {len(all_results)} raw results")
    return all_results
