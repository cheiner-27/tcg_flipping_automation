from rapidfuzz import fuzz, process

# Product name substrings that indicate non-single-card products
NAME_EXCLUDE = [
    'Booster', '3 Pack', 'Blister', 'Battle Box', 'Exclusive',
    'Elite Trainer', 'Mini Tin', 'Collection', 'Theme Deck',
    'Set of',
]

# Exact group names to exclude
GROUP_EXCLUDE_EXACT = {
    'POP Series 1', 'POP Series 2', 'POP Series 3', 'POP Series 4',
    'POP Series 5', 'POP Series 6', 'POP Series 7', 'POP Series 8',
    'POP Series 9', 'Prize Pack Series Cards',
    'Trick or Trade BOOster Bundle 2023', 'Trick or Trade BOOster Bundle 2024',
}

# Substrings in group name that trigger exclusion
GROUP_EXCLUDE_CONTAINS = ['Jumbo', 'Championship']

# Fuzzy match threshold (mirrors PowerQuery's Threshold=0.89, scaled to 0–100)
DISMISSED_THRESHOLD = 89


PRICE_RATIO_THRESHOLD = 10
PRICE_RATIO_MARKET_FLOOR = 200


def _passes_name_filter(name: str) -> bool:
    lower = name.lower()
    return not any(term.lower() in lower for term in NAME_EXCLUDE)


def _passes_group_filter(group: str) -> bool:
    if group in GROUP_EXCLUDE_EXACT:
        return False
    lower = group.lower()
    return not any(term.lower() in lower for term in GROUP_EXCLUDE_CONTAINS)


def _passes_price_ratio_filter(row: dict) -> bool:
    """Exclude cards where marketPrice/lowPrice > 10, unless marketPrice > $200."""
    market = row.get('marketPrice')
    low = row.get('lowPrice')
    try:
        market_f = float(market)
        low_f = float(low)
    except (TypeError, ValueError):
        return True  # missing price data — don't exclude
    if low_f <= 0:
        return True
    if market_f / low_f > PRICE_RATIO_THRESHOLD and market_f <= PRICE_RATIO_MARKET_FLOOR:
        return False
    return True


def filter_tcg_data(tcg_data: list, dismissed_terms: list) -> list:
    """
    Apply product/group exclusions, price-ratio filter, and remove dismissed
    cards via fuzzy match.

    tcg_data:        list of dicts from tcgcsv_scraper.fetch_tcg_data
    dismissed_terms: list of search_term strings pulled from Supabase
    """
    candidates = [
        row for row in tcg_data
        if _passes_name_filter(row['name'])
        and _passes_group_filter(row['group'])
        and _passes_price_ratio_filter(row)
    ]

    if not dismissed_terms:
        print(f"Filtered to {len(candidates)} products (no dismissed cards to check)")
        return candidates

    # rapidfuzz.process.extractOne is vectorised in C — much faster than a Python loop
    results = []
    for row in candidates:
        match = process.extractOne(
            row['searchTerm'],
            dismissed_terms,
            scorer=fuzz.ratio,
            score_cutoff=DISMISSED_THRESHOLD,
        )
        if match is None:
            results.append(row)

    print(f"Filtered to {len(results)} products "
          f"({len(tcg_data) - len(results)} removed, {len(tcg_data)} total)")
    return results
