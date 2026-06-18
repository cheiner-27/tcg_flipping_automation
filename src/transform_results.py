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

# MTG print-variant qualifiers: like 'foil', if one is in the search term the
# listing title must also contain it (otherwise it's the wrong printing).
MAGIC_VARIANT_KEYWORDS = [
    'borderless', 'extended art', 'halo foil', 'foil etched',
    'textured foil', 'galaxy foil', 'surge foil', 'confetti foil',
]

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

    Magic collector numbers can carry a letter suffix (e.g. '410c', '0147c').
    The suffix is honored so variants don't cross-match:
      * ext_num '147c' matches '147c' or a bare '147', but NOT '147d';
      * ext_num '147' (no suffix) matches '147' but NOT '147c' (a variant).
    """
    m = re.search(r'(\d+)([a-z])?', (ext_num or '').lower())
    if not m:
        return True
    num = str(int(m.group(1)))
    suffix = m.group(2) or ''
    # A bare number is always allowed; a wrong letter suffix is rejected.
    tail = (f'(?:{suffix})?' if suffix else '') + r'(?![0-9a-z])'
    return bool(re.search(r'(?<!\d)0*' + num + tail, title_lower))


# Collector-number tokens in a listing title. We only trust strong signals so
# that years (1994), set totals (/350) and vendor stock ids ('ID# 517456') are
# not mistaken for a card number:
#   * '#N'  — the '#' must NOT follow a letter/digit, so 'ID# 517456' is ignored
#   * 'N/M' — both sides captured (the printed number can be on either side,
#             e.g. '(2016/20)'); leading zeros tolerated
# Numbers are capped at 4 digits, which also drops 6-digit stock ids and keeps
# every real collector number.
_HASH_NUM  = re.compile(r'(?<![a-z0-9])#\s*0*(\d{1,4})(?!\d)')
_SLASH_NUM = re.compile(r'(?<![a-z0-9/])0*(\d{1,4})\s*/\s*0*(\d{1,4})(?!\d)')


def _title_collector_numbers(title_lower: str) -> set:
    """Collector-number candidates parsed from a listing title (see patterns)."""
    nums = {int(m) for m in _HASH_NUM.findall(title_lower)}
    for a, b in _SLASH_NUM.findall(title_lower):
        nums.add(int(a))
        nums.add(int(b))
    return nums


def _title_is_foil(title_lower: str) -> bool:
    """True if the title says 'foil' but not 'non-foil'/'nonfoil'/'non foil'."""
    return 'foil' in re.sub(r'non[\s-]*foil', '', title_lower)


def _title_has_required_keywords(search_lower: str, title_lower: str, keywords: list) -> bool:
    """For each keyword present in the search term, require it in the title."""
    return all(kw not in search_lower or kw in title_lower for kw in keywords)


# Words ignored when matching Magic set names against titles: colors, grades,
# fillers, and generic MTG vocabulary that don't identify a specific set.
_SET_STOPWORDS = set(
    'the of and a an or to for from with in on at by magic mtg card cards game '
    'gathering set sets edition tcg commander deck decks promo promos league duel '
    'core box pack series collection special white blue black red green colorless '
    'mint near rare uncommon common mythic foil nonfoil english playset bonus custom '
    'case sharp corners clean duty old school free regular lightly played'.split()
)


def _set_tokens(text: str) -> set:
    """Word tokens from a set name / title, keeping 4-digit years and words >=4
    chars that aren't set-name stopwords."""
    out = set()
    for w in re.split(r'[^a-z0-9]+', (text or '').lower()):
        if not w:
            continue
        if re.fullmatch(r'\d{4}', w):
            out.add(w)
        elif len(w) >= 4 and w not in _SET_STOPWORDS:
            out.add(w)
    return out


def build_set_token_model(tcg_data: list) -> dict:
    """
    From all TCG group (set) names, find tokens that uniquely identify ONE set.

    Returns {'owner': {token: group}, 'group_pos': {group: set(tokens)}}, used to
    recognize a card's own set in a listing title (a positive match signal) and to
    detect a *different* set named in the title (a wrong-printing signal). Tokens
    shared by multiple sets are dropped, so only distinctive set words remain.
    """
    from collections import defaultdict
    tok_groups: dict = defaultdict(set)
    groups = {row['group'] for row in tcg_data if row.get('group')}
    for g in groups:
        for w in _set_tokens(g):
            tok_groups[w].add(g)
    owner = {w: next(iter(gs)) for w, gs in tok_groups.items() if len(gs) == 1}
    group_pos = {g: {w for w in _set_tokens(g) if w in owner} for g in groups}
    return {'owner': owner, 'group_pos': group_pos}


def _title_set_signals(title_lower: str, group: str, card_name: str, model: dict):
    """
    Return (names_our_set, names_other_set) for a Magic listing title.

    Tokens that appear in the card's own name are ignored (so a card called
    'The Ur-Dragon' isn't read as the set "Dragon's Maze"), and 4-digit years are
    ignored for the other-set signal (to avoid e.g. an SDCC '2016' reading as
    "Commander 2016").
    """
    title_toks = _set_tokens(title_lower)
    card_toks = {w for w in re.split(r'[^a-z0-9]+', (card_name or '').lower()) if len(w) >= 3}
    pos = model['group_pos'].get(group, set()) - card_toks
    has_our = bool(pos & title_toks)
    owner = model['owner']
    has_other = any(
        not re.fullmatch(r'\d{4}', w) and w not in card_toks
        and owner.get(w) and owner[w] != group
        for w in title_toks
    )
    return has_our, has_other


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
            '_set_group':           tcg.get('group', ''),
            '_card_name':           tcg.get('name', ''),
        })

    print(f"Merged {len(output)} eBay results with TCG data")
    return output


def apply_filters(merged_results: list, category: str = 'pokemon',
                  set_model: dict | None = None) -> list:
    """
    Apply all content and time filters to already-merged results.
    Items without a known end date (pure BIN listings) are kept — only
    items with a confirmed end date beyond MAX_AUCTION_DAYS are dropped.

    set_model (Magic only): output of build_set_token_model(tcg_data). When
    provided, a listing is kept if its title shows the collector number OR a
    distinctive word from the card's set, AND does not name a different set.
    When omitted, the collector number alone is required (legacy behavior).
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
            ext_num = row.get('_ext_num', '')
            has_number = _title_has_number(ext_num, title_lower)
            # Alphanumeric collector numbers (e.g. '17c', '410d') only differ from
            # their sibling variants by the number itself, so a set-name match
            # can't be allowed to rescue them — the number must be in the title.
            is_alnum_num = bool(re.search(r'\d', ext_num)) and bool(re.search(r'[a-z]', ext_num.lower()))
            if set_model is not None:
                has_set, names_other = _title_set_signals(
                    title_lower, row.get('_set_group', ''), row.get('_card_name', ''), set_model)
                # Right card needs its number (always, for alphanumeric numbers)
                # OR its set in the title …
                if not (has_number or (has_set and not is_alnum_num)):
                    continue
                # … and must not advertise a different set (wrong reprint).
                if names_other:
                    continue
            elif not has_number:
                continue
            # If the title carries plain collector numbers and none matches this
            # card's (numeric) number, it's a different card — drop it.
            if ext_num.isdigit():
                title_nums = _title_collector_numbers(title_lower)
                if title_nums and int(ext_num) not in title_nums:
                    continue
            subtype = (row.get(f'{prefix}.subTypeName') or '').lower()
            if 'foil' in subtype and not _title_is_foil(title_lower):
                continue
            if not _title_has_required_keywords(search_lower, title_lower, MAGIC_VARIANT_KEYWORDS):
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
