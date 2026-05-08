import re
from datetime import timedelta

import config

# Title exclusion lists — all matched case-insensitively against lowercased title
GRADING_TERMS    = ['psa', 'cgc', 'bgs']
CONDITION_TERMS  = [' mp', '/mp', ' hp', '/hp', 'moderate', 'heavily', 'heavy', '(hp)', 'lp-', ' lp', 'lightly']
DAMAGE_TERMS     = ['dmg', 'damage', 'see photo']
LANGUAGE_TERMS   = ['japan', 'japanese', 'jpn', 'korean', 'chinese', 'spanish', 'italian', '(cn)', 'portuguese']
JUMBO_TERMS      = ['jumbo', 'oversized']
SEARCH_TERM_EXCL = ['diy', 'hand drawn']

MAX_TIME_SECONDS = config.MAX_AUCTION_DAYS * 24 * 3600


def _title_has(title_lower: str, terms: list) -> bool:
    return any(t in title_lower for t in terms)


def _swsh_check(search_term: str, title: str) -> bool:
    pos = search_term.upper().find('SWSH')
    if pos == -1:
        return True
    after = pos + 4
    if len(search_term) < after + 3:
        return True
    return search_term[after:after + 3] in title


def _prefix_num_check(search_term: str, title: str, prefix: str) -> bool:
    pattern = re.compile(re.escape(prefix) + r'(\d+)', re.IGNORECASE)
    codes_search = {m.group(1) for m in pattern.finditer(search_term)}
    if not codes_search:
        return True
    codes_title = {m.group(1) for m in pattern.finditer(title)}
    if not codes_title:
        return True
    return codes_search.issubset(codes_title)


def _format_duration(seconds: float | None) -> str:
    if seconds is None:
        return ''
    td = timedelta(seconds=seconds)
    hours, rem = divmod(td.seconds, 3600)
    return f'{td.days}d {hours}h {rem // 60}m'


def merge_with_tcg(ebay_results: list, tcg_data: list, category: str) -> list:
    """
    Merge eBay results with TCG data and compute totals/ROI.
    No content filters are applied — this produces the full raw merged output
    that matches the old PowerQuery format (columns: tcglist_{category}.X, etc.).

    The returned dicts also include '_time_remaining_seconds' (prefixed with _)
    as an internal field used by apply_filters(); it is excluded from CSV output
    via extrasaction='ignore'.
    """
    prefix = f'tcglist_{category}'
    tcg_lookup = {row['searchTerm']: row for row in tcg_data}
    output = []

    for item in ebay_results:
        tcg = tcg_lookup.get(item['search_term'])
        if not tcg:
            continue

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

        try:
            low_price = float(tcg['lowPrice']) if tcg['lowPrice'] is not None else None
        except (TypeError, ValueError):
            low_price = None

        bin_total     = (bin_price + shipping) if bin_price is not None else None
        auction_total = (auction_price + shipping) if auction_price is not None else None
        roi = (bin_total / low_price) if (bin_total is not None and low_price and low_price > 0) else None

        time_secs = item.get('time_remaining_seconds')

        output.append({
            'search_term':          item['search_term'],
            'item_id':              item['item_id'],
            'title':                item.get('title') or '',
            'auction_price':        auction_price,
            'buy_it_now_price':     bin_price,
            'shipping_cost':        shipping,
            'url':                  item.get('url', ''),
            f'{prefix}.productId':  tcg['productId'],
            f'{prefix}.searchTerm': tcg['searchTerm'],
            f'{prefix}.url':        tcg['url'],
            f'{prefix}.subTypeName': tcg['subTypeName'],
            f'{prefix}.lowPrice':   low_price,
            f'{prefix}.midPrice':   tcg.get('midPrice'),
            f'{prefix}.marketPrice': tcg.get('marketPrice'),
            'Total Time':           _format_duration(time_secs),
            'buy_it_now_total':     bin_total,
            'auction_total':        auction_total,
            'ROI':                  roi,
            # Internal — excluded from CSV via extrasaction='ignore'
            '_time_remaining_seconds': time_secs,
        })

    print(f"Merged {len(output)} eBay results with TCG data")
    return output


def apply_filters(merged_results: list) -> list:
    """
    Apply all content and time filters to already-merged results.
    Items without a known end date (pure BIN listings) are kept — only
    items with a confirmed end date beyond MAX_AUCTION_DAYS are dropped.
    """
    output = []

    for row in merged_results:
        title = row['title']
        title_lower = title.lower()
        search_term = row['search_term']
        search_lower = search_term.lower()

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
        if _title_has(search_lower, SEARCH_TERM_EXCL):
            continue
        if 'jumbo' in search_lower:
            continue

        if 'shadowless' in search_lower:
            if 'shadowless' not in title_lower and 'bss' not in title_lower:
                continue

        if not _swsh_check(search_term, title):
            continue
        if not all(_prefix_num_check(search_term, title, p) for p in ('XY', 'SM', 'BW', 'DP')):
            continue

        # Only drop items whose known end date is beyond the cutoff.
        # Items with no end date (BIN listings) pass through.
        time_secs = row.get('_time_remaining_seconds')
        if time_secs is not None and time_secs > MAX_TIME_SECONDS:
            continue

        output.append(row)

    print(f"Filtered to {len(output)} results from {len(merged_results)} merged items")
    return output
