import re
from datetime import timedelta

import config

# Title exclusion lists — all matched case-insensitively against lowercased title
GRADING_TERMS     = ['psa', 'cgc', 'bgs']
CONDITION_TERMS   = [' mp', '/mp', ' hp', '/hp', 'moderate', 'heavily', 'heavy', '(hp)', 'lp-']
DAMAGE_TERMS      = ['dmg', 'damage']
LANGUAGE_TERMS    = ['japan', 'japanese', 'jpn', 'korean', 'chinese', 'spanish', 'italian', '(cn)']
JUMBO_TERMS       = ['jumbo', 'oversized']
SEARCH_TERM_EXCL  = ['diy', 'hand drawn']  # checked against search_term

MAX_TIME_SECONDS  = config.MAX_AUCTION_DAYS * 24 * 3600


def _title_has(title_lower: str, terms: list) -> bool:
    return any(t in title_lower for t in terms)


def _swsh_check(search_term: str, title: str) -> bool:
    """
    If search_term contains 'SWSH' followed by at least 3 chars, the title
    must contain those 3 chars. Mirrors the original Power Query logic exactly.
    """
    pos = search_term.upper().find('SWSH')
    if pos == -1:
        return True
    after = pos + 4
    if len(search_term) < after + 3:
        return True  # not enough chars to extract a code → pass
    code = search_term[after:after + 3]
    return code in title


def _prefix_num_check(search_term: str, title: str, prefix: str) -> bool:
    """
    Extract all PREFIX+digits tokens from search_term and title.
    - If search_term has none: pass.
    - If title has none:       pass (can't verify — seller omitted card code).
    - Otherwise: all codes from search_term must appear in title.
    """
    pattern = re.compile(re.escape(prefix) + r'(\d+)', re.IGNORECASE)
    codes_search = {m.group(1) for m in pattern.finditer(search_term)}
    if not codes_search:
        return True
    codes_title = {m.group(1) for m in pattern.finditer(title)}
    if not codes_title:
        return True
    return codes_search.issubset(codes_title)


def _format_duration(seconds: float) -> str:
    td = timedelta(seconds=seconds)
    days = td.days
    hours, rem = divmod(td.seconds, 3600)
    minutes = rem // 60
    return f'{days}d {hours}h {minutes}m'


def transform_results(ebay_results: list, tcg_data: list) -> list:
    """
    Merge eBay results with TCG data, apply all filters, and compute
    buy_it_now_total, auction_total, and ROI.

    tcg_data is the FULL unfiltered list so every search_term has a match.
    """
    tcg_lookup = {row['searchTerm']: row for row in tcg_data}
    output = []

    for item in ebay_results:
        search_term = item['search_term']
        title = item.get('title') or ''
        title_lower = title.lower()

        # Must have a matching TCG row to compute ROI
        tcg = tcg_lookup.get(search_term)
        if not tcg:
            continue

        # --- Title content filters ---
        if _title_has(title_lower, GRADING_TERMS):
            continue
        if _title_has(title_lower, CONDITION_TERMS):
            continue
        if _title_has(title_lower, DAMAGE_TERMS):
            continue
        if _title_has(title_lower, LANGUAGE_TERMS):
            continue
        if 'art case' in title_lower:
            continue
        if _title_has(title_lower, JUMBO_TERMS):
            continue

        # --- Search-term filters ---
        search_lower = search_term.lower()
        if _title_has(search_lower, SEARCH_TERM_EXCL):
            continue
        if 'jumbo' in search_lower:
            continue

        # --- Shadowless: if search requires it, title must confirm it ---
        if 'shadowless' in search_lower:
            if 'shadowless' not in title_lower and 'bss' not in title_lower:
                continue

        # --- Card-series prefix checks ---
        if not _swsh_check(search_term, title):
            continue
        if not all(_prefix_num_check(search_term, title, p) for p in ('XY', 'SM', 'BW', 'DP')):
            continue

        # --- Time filter: keep only items ending within MAX_AUCTION_DAYS ---
        time_secs = item.get('time_remaining_seconds')
        if time_secs is None or time_secs > MAX_TIME_SECONDS:
            continue

        # --- Compute totals ---
        try:
            shipping = float(item['shipping_cost']) if item['shipping_cost'] is not None else 0.0
        except (TypeError, ValueError):
            shipping = 0.0

        try:
            bin_price = float(item['buy_it_now_price']) if item['buy_it_now_price'] is not None else None
        except (TypeError, ValueError):
            bin_price = None

        try:
            auction_price = float(item['auction_price']) if item['auction_price'] is not None else None
        except (TypeError, ValueError):
            auction_price = None

        bin_total     = (bin_price + shipping) if bin_price is not None else None
        auction_total = (auction_price + shipping) if auction_price is not None else None

        try:
            low_price = float(tcg['lowPrice']) if tcg['lowPrice'] is not None else None
        except (TypeError, ValueError):
            low_price = None

        roi = (bin_total / low_price) if (bin_total is not None and low_price and low_price > 0) else None

        output.append({
            'search_term':       search_term,
            'item_id':           item['item_id'],
            'title':             title,
            'auction_price':     auction_price,
            'buy_it_now_price':  bin_price,
            'shipping_cost':     shipping,
            'time_remaining':    _format_duration(time_secs),
            'url':               item['url'],
            'card_condition':    item.get('card_condition', ''),
            'tcg_product_id':    tcg['productId'],
            'tcg_url':           tcg['url'],
            'subTypeName':       tcg['subTypeName'],
            'lowPrice':          low_price,
            'midPrice':          tcg.get('midPrice'),
            'marketPrice':       tcg.get('marketPrice'),
            'buy_it_now_total':  bin_total,
            'auction_total':     auction_total,
            'roi':               roi,
        })

    print(f"Transform complete: {len(output)} results kept from {len(ebay_results)} raw items")
    return output
