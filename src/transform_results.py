import re
from datetime import timedelta

import config

TCG_IMAGE_BASE = 'https://product-images.tcgplayer.com/fit-in/437x437'


def _outbound_shipping(price: float) -> float:
    """USPS shipping cost when reselling the card."""
    if price < 25:
        return 1.50
    if price <= 200:
        return 5.50
    return 10.0 + int((price - 200) / 100)


def _profit_roi(bin_total: float, mid_or_market: float) -> float:
    """Buy-on-eBay / sell-on-TCG ROI after all fees and shipping."""
    purchase_price = bin_total * 1.06          # eBay price + 6% tax/fees
    tcg_revenue = mid_or_market * 0.8775       # TCG proceeds after 12.25% fees
    profit = tcg_revenue - 0.30 - purchase_price - _outbound_shipping(mid_or_market)
    return profit / purchase_price

# Title exclusion lists — all matched case-insensitively against lowercased title
GRADING_TERMS    = ['psa', 'cgc', 'bgs']
CONDITION_TERMS  = [' mp', '/mp', '-mp', ' hp', '/hp', '-hp', 'moderate', 'heavily', 'heavy', '(hp)', 'lp-', ' lp', '-lp', 'lightly', '(lp)']
DAMAGE_TERMS     = ['dmg', 'damage', 'see photo']
LANGUAGE_TERMS   = ['japan', 'japanese', 'jpn', 'korean', 'chinese', 'spanish', 'italian', '(cn)', 'portuguese']
JUMBO_TERMS      = ['jumbo', 'oversized']
QUANTITY_TERMS   = ['set of', 'lot of']
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


def _title_has_number(ext_num: str, title_lower: str) -> bool:
    """
    True if the card's collector number appears in the title as a standalone
    number (tolerating leading zeros and '#'), e.g. '78' matches '78', '#78',
    '078', '78/264' — but not '780' or '1782'. Cards with no numeric ext_num
    always pass.
    """
    m = re.search(r'\d+', ext_num or '')
    if not m:
        return True
    num = str(int(m.group()))
    return bool(re.search(r'(?<!\d)0*' + num + r'(?!\d)', title_lower))


def _title_is_foil(title_lower: str) -> bool:
    """True if the title says 'foil' but not 'non-foil'/'nonfoil'/'non foil'."""
    return 'foil' in re.sub(r'non[\s-]*foil', '', title_lower)


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

        try:
            mid_price = float(tcg['midPrice']) if tcg.get('midPrice') is not None else None
        except (TypeError, ValueError):
            mid_price = None

        try:
            market_price = float(tcg['marketPrice']) if tcg.get('marketPrice') is not None else None
        except (TypeError, ValueError):
            market_price = None

        mid_or_market = market_price if market_price is not None else mid_price

        bin_total     = (bin_price + shipping) if bin_price is not None else None
        auction_total = (auction_price + shipping) if auction_price is not None else None
        roi = (bin_total / low_price) if (bin_total is not None and low_price and low_price > 0) else None

        calc_profit_roi = None
        if bin_total is not None and bin_total > 0 and mid_or_market and mid_or_market > 0:
            ratio = bin_total / mid_or_market
            if 0.5 <= ratio <= 2.0:
                calc_profit_roi = _profit_roi(bin_total, mid_or_market)

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
            f'{prefix}.midPrice':   mid_price,
            f'{prefix}.marketPrice': market_price,
            'Total Time':           _format_duration(time_secs),
            'buy_it_now_total':     bin_total,
            'auction_total':        auction_total,
            'ROI':                  roi,
            'profit_roi':           calc_profit_roi,
            'ebay_image_url':       item.get('image_url', ''),
            'tcg_image_url':        f'{TCG_IMAGE_BASE}/{tcg["productId"]}.jpg',
            # Internal — excluded from CSV via extrasaction='ignore'
            '_time_remaining_seconds': time_secs,
            '_ext_num':             tcg.get('ext_num', ''),
        })

    print(f"Merged {len(output)} eBay results with TCG data")
    return output


def apply_filters(merged_results: list, category: str = 'pokemon') -> list:
    """
    Apply all content and time filters to already-merged results.
    Items without a known end date (pure BIN listings) are kept — only
    items with a confirmed end date beyond MAX_AUCTION_DAYS are dropped.
    """
    output = []
    is_pokemon = category == 'pokemon'
    is_magic = category == 'magic'
    prefix = f'tcglist_{category}'

    for row in merged_results:
        title = row['title']
        title_lower = title.lower()
        search_term = row['search_term']
        search_lower = search_term.lower()

        # Only keep listings with a BIN price and sufficient profit ROI
        if row.get('buy_it_now_total') is None:
            continue
        profit_roi = row.get('profit_roi')
        if profit_roi is None or profit_roi < config.MIN_ROI:
            continue

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
        if _title_has(title_lower, QUANTITY_TERMS):
            continue
        if _title_has(search_lower, SEARCH_TERM_EXCL):
            continue
        if 'jumbo' in search_lower:
            continue

        # Magic-specific checks: the collector number must appear in the title,
        # and foil cards must be sold as foil.
        if is_magic:
            if not _title_has_number(row.get('_ext_num', ''), title_lower):
                continue
            subtype = (row.get(f'{prefix}.subTypeName') or '').lower()
            if 'foil' in subtype and not _title_is_foil(title_lower):
                continue

        # Pokemon-specific title/term checks
        if is_pokemon:
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
