# ── Pokemon exclusions ────────────────────────────────────────────────────────

_POKEMON_NAME_EXCLUDE = [
    'Booster', '3 Pack', 'Blister', 'Battle Box', 'Exclusive',
    'Elite Trainer', ' Tin', 'Collection', 'Theme Deck',
    'Set of', 'Battle Deck', 'V Battle', 'League Battle',
    'Starter Set', 'Starter Deck', 'Collector Chest', 'Case File',
    'Gift Box', 'Figure', 'Playmat', 'Binder',
]

_POKEMON_GROUP_EXCLUDE_EXACT = {
    'POP Series 1', 'POP Series 2', 'POP Series 3', 'POP Series 4',
    'POP Series 5', 'POP Series 6', 'POP Series 7', 'POP Series 8',
    'POP Series 9', 'Prize Pack Series Cards',
    'Trick or Trade BOOster Bundle 2023', 'Trick or Trade BOOster Bundle 2024',
}

_POKEMON_GROUP_EXCLUDE_CONTAINS = ['Jumbo', 'Championship']

# ── Magic: The Gathering exclusions ──────────────────────────────────────────

_MAGIC_NAME_EXCLUDE = [
    # Sealed products
    'Booster', 'Bundle', 'Commander Deck', 'Starter Kit', 'Starter Deck',
    'Starter Set', 'Theme Deck', 'Fat Pack', 'Gift Pack', 'Gift Set',
    'Prerelease Pack', 'Promo Pack', 'Tournament Pack', 'Intro Pack',
    'Event Deck', 'Deck Box', 'Deckbox', 'Playmat', 'Sleeves', 'Binder',
    'Dice', 'Display', 'Case', 'Sealed', 'Box Set', 'Box Topper',
    'Oversized', 'Life Counter', 'Spindown', ' Deck', 'Edition Pack',
    'Edition Box', 'Countdown Kit', 'Collection:', 'Scene Box', 'Clash Pack',
    '- Tin', 'Commander Kit', 'Beginner Box',
    # Non-singles
    ' Token', 'Emblem', 'Checklist', 'Art Card', 'Punch Card',
    # Other
    'Oversize',
]

_MAGIC_GROUP_EXCLUDE_EXACT: set = set()

_MAGIC_GROUP_EXCLUDE_CONTAINS = ['Jumbo', 'Oversize', 'Championship', 'Secret Lair']

# ── Per-game lookup tables ────────────────────────────────────────────────────

_NAME_EXCLUDE = {
    'pokemon': _POKEMON_NAME_EXCLUDE,
    'magic':   _MAGIC_NAME_EXCLUDE,
}

_GROUP_EXCLUDE_EXACT = {
    'pokemon': _POKEMON_GROUP_EXCLUDE_EXACT,
    'magic':   _MAGIC_GROUP_EXCLUDE_EXACT,
}

_GROUP_EXCLUDE_CONTAINS = {
    'pokemon': _POKEMON_GROUP_EXCLUDE_CONTAINS,
    'magic':   _MAGIC_GROUP_EXCLUDE_CONTAINS,
}

PRICE_RATIO_THRESHOLD    = 10
PRICE_RATIO_MARKET_FLOOR = 200


def _passes_name_filter(name: str, category: str) -> bool:
    terms = _NAME_EXCLUDE.get(category, _POKEMON_NAME_EXCLUDE)
    lower = name.lower()
    return not any(term.lower() in lower for term in terms)


def _passes_group_filter(group: str, category: str) -> bool:
    if group in _GROUP_EXCLUDE_EXACT.get(category, set()):
        return False
    lower = group.lower()
    return not any(term.lower() in lower for term in _GROUP_EXCLUDE_CONTAINS.get(category, []))


def _passes_price_ratio_filter(row: dict) -> bool:
    """Exclude cards where marketPrice/lowPrice > 10, unless marketPrice > $200."""
    market = row.get('marketPrice')
    low = row.get('lowPrice')
    try:
        market_f = float(market)
        low_f = float(low)
    except (TypeError, ValueError):
        return True
    if low_f <= 0:
        return True
    if market_f / low_f > PRICE_RATIO_THRESHOLD and market_f <= PRICE_RATIO_MARKET_FLOOR:
        return False
    return True


def _normalize(term: str) -> str:
    """Strip quotes and collapse whitespace for exact dismissed-card matching."""
    return ' '.join(term.replace('"', '').split()).lower()


def filter_tcg_data(tcg_data: list, dismissed_terms: list, category: str = 'pokemon') -> list:
    """
    Apply product/group exclusions, price-ratio filter, and remove dismissed cards.

    tcg_data:        list of dicts from tcgcsv_scraper.fetch_tcg_data
    dismissed_terms: list of search_term strings pulled from Supabase
    category:        game name ('pokemon' or 'magic')
    """
    candidates = [
        row for row in tcg_data
        if _passes_name_filter(row['name'], category)
        and _passes_group_filter(row['group'], category)
        and _passes_price_ratio_filter(row)
    ]

    if not dismissed_terms:
        print(f"Filtered to {len(candidates)} products (no dismissed cards to check)")
        return candidates

    dismissed_set = {_normalize(t) for t in dismissed_terms}
    results = [row for row in candidates if _normalize(row['searchTerm']) not in dismissed_set]

    print(f"Filtered to {len(results)} products "
          f"({len(tcg_data) - len(results)} removed, {len(tcg_data)} total)")
    return results
