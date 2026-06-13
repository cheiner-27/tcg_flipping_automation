import re
import time
import requests

CATEGORIES = {
    'magic': '1',
    'yugioh': '2',
    'pokemon': '3',
    'lorcana': '72',
}

HEADERS = {"User-Agent": "TCGFlippingAutomation/1.0.0"}
REQUEST_DELAY = 0.1  # seconds between requests, per tcgcsv.com usage guidelines

_QUOTE_PATTERN = re.compile(r'\b(prerelease|staff|promo)\b', re.IGNORECASE)


def _quote_special_terms(search_term: str) -> str:
    """Wrap prerelease/staff/promo in quotes so eBay treats them as required."""
    return _QUOTE_PATTERN.sub(lambda m: f'"{m.group(0)}"', search_term)


def _get(url):
    r = requests.get(url, headers=HEADERS)
    r.raise_for_status()
    time.sleep(REQUEST_DELAY)
    return r


# ── Pokemon search term builder ───────────────────────────────────────────────

def _build_pokemon_search_term(product_name: str, ext_num: str, group_name: str,
                                sub_type: str) -> str:
    """Build eBay search term for a Pokemon card."""
    display_group = group_name
    if '-' in display_group:
        display_group = display_group.split('-')[1].lstrip()
    elif ':' in display_group and display_group.index(':') < 7:
        display_group = display_group.split(': ')[1].lstrip()

    name = product_name

    # Expedition sets embed card numbers in parentheses — remove them
    if group_name == 'Expedition':
        start = name.find('(')
        end = name.find(')')
        if start != -1 and end != -1:
            name = name[:start] + name[end + 1:]

    try:
        if ext_num and ext_num in name:
            name = name.replace(ext_num, '')
        if name.startswith(display_group):
            name = name[len(display_group):].strip()
        if ' tin' in name.lower() or ' box' in name.lower() or 'booster' in name.lower():
            return ''  # caller skips empty string
    except Exception:
        pass

    name = (name
            .replace('(', '').replace(')', '')
            .replace('[', '').replace(']', '')
            .replace(' - ', ' ')
            .replace('-', ' ')
            .replace('  ', ' ')
            .strip())

    try:
        if '/' not in ext_num or ext_num == '':
            if sub_type == 'Normal':
                term = f'{name} {display_group} {ext_num}'.strip()
            elif sub_type == 'Holofoil':
                term = f'{name} {display_group} {ext_num} holo'.strip()
            elif sub_type == 'Reverse Holofoil':
                term = f'{name} {display_group} {ext_num} reverse holo'.strip()
            else:
                term = f'{name} {display_group} {ext_num}'.strip()
        elif display_group == 'Miscellaneous Cards & Products':
            term = name
        elif sub_type == 'Normal':
            term = f'{name} "{ext_num}" {display_group}'
        elif sub_type == 'Holofoil':
            term = f'{name} "{ext_num}" {display_group} holo'
        elif sub_type == 'Reverse Holofoil':
            term = f'{name} "{ext_num}" {display_group} reverse holo'
        else:
            term = f'{name} "{ext_num}" {display_group}'
    except Exception:
        term = f'{product_name} {display_group}'

    return _quote_special_terms(term)


# ── MTG search term builder ───────────────────────────────────────────────────

_PROMO_EDITION_PATTERN = re.compile(r'\b(promo|edition)', re.IGNORECASE)


def _clean_set_name(group_name: str) -> str:
    """
    Trim a set name to its core identifier for use as a quoted phrase when a card
    has no collector number:
      1a. drop everything from the first colon onward ("Ravnica: Clue Edition" -> "Ravnica")
      1b. drop everything from 'Promo'/'Edition' onward ("FNM Promo" -> "FNM")
    Falls back to the original name if trimming would leave nothing.
    """
    name = group_name.split(':')[0]
    m = _PROMO_EDITION_PATTERN.search(name)
    if m:
        name = name[:m.start()]
    name = name.strip()
    return name or group_name.strip()


def _build_mtg_search_term(product_name: str, ext_num: str, group_name: str,
                            sub_type: str) -> str:
    """Build eBay search term for a Magic: The Gathering card."""
    name = product_name  # MTG card names are already clean — no stripping needed

    # Some product names embed the collector number in parentheses, e.g.
    # "Lightning Bolt (185)" with Number 185 — drop it so it isn't duplicated.
    if ext_num:
        name = name.replace(f'({ext_num})', '')
        name = ' '.join(name.split())

    foil_suffix = ''
    sub_lower = (sub_type or '').lower()
    if 'etched' in sub_lower:
        foil_suffix = ' etched foil'
    elif 'foil' in sub_lower:
        foil_suffix = ' foil'

    if ext_num:
        # Number left unquoted (quoting over-narrows eBay); transform_results
        # requires it to appear in the listing title instead.
        term = f'{name} {ext_num} {group_name}{foil_suffix}'
    else:
        # No collector number: quote the trimmed set name as the disambiguator.
        term = f'{name} "{_clean_set_name(group_name)}"{foil_suffix}'

    return _quote_special_terms(term)


# ── Main fetcher ──────────────────────────────────────────────────────────────

def fetch_tcg_data(category_name, min_price=None, max_price=None):
    category_id = CATEGORIES.get(category_name.lower())
    if not category_id:
        raise ValueError(f"Unknown category: {category_name!r}. Valid: {list(CATEGORIES)}")

    is_magic = category_name.lower() == 'magic'

    all_groups = _get(f"https://tcgcsv.com/tcgplayer/{category_id}/groups").json()['results']

    all_data = []

    for group in all_groups:
        group_id = group['groupId']
        group_name = group['name']

        products = _get(f"https://tcgcsv.com/tcgplayer/{category_id}/{group_id}/products").json()['results']
        prices = _get(f"https://tcgcsv.com/tcgplayer/{category_id}/{group_id}/prices").json()['results']

        price_dict = {p['productId']: p for p in prices}

        for product in products:
            product_id = product['productId']
            product_name = product['name']
            clean_name = product['cleanName']

            ext_num = ''
            for data in product.get('extendedData') or []:
                if data['name'] == 'Number':
                    ext_num = data['value']
                    break

            price_info = price_dict.get(product_id, {})
            sub_type = price_info.get('subTypeName', 'N/A')

            if is_magic:
                search_term = _build_mtg_search_term(product_name, ext_num, group_name, sub_type)
            else:
                search_term = _build_pokemon_search_term(product_name, ext_num, group_name, sub_type)
                if not search_term:
                    continue  # skipped by inline filter in Pokemon builder

            low_price = price_info.get('lowPrice')
            mid_price = price_info.get('midPrice')
            market_price = price_info.get('marketPrice')

            try:
                market_price_value = float(market_price) if market_price is not None else None
            except (ValueError, TypeError):
                market_price_value = None

            if min_price is not None and max_price is not None:
                if market_price_value is None or not (min_price <= market_price_value <= max_price):
                    continue

            all_data.append({
                'productId': product_id,
                'group': group_name,
                'name': product_name,
                'ext_num': ext_num,
                'cleanName': clean_name,
                'searchTerm': search_term,
                'url': product['url'],
                'subTypeName': sub_type,
                'lowPrice': low_price,
                'midPrice': mid_price,
                'marketPrice': market_price,
            })

    print(f"Fetched {len(all_data)} products for '{category_name}' (price ${min_price}–${max_price})")
    return all_data
