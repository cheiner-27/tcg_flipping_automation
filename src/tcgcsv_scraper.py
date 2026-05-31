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


def fetch_tcg_data(category_name, min_price=None, max_price=None):
    category_id = CATEGORIES.get(category_name.lower())
    if not category_id:
        raise ValueError(f"Unknown category: {category_name!r}. Valid: {list(CATEGORIES)}")

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

            # Normalize group display name: strip leading "X - " or "X: " prefixes
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
                    continue
            except Exception:
                pass

            name = (name
                    .replace('(', '').replace(')', '')
                    .replace('[', '').replace(']', '')
                    .replace(' - ', ' ')
                    .replace('-', ' ')
                    .replace('  ', ' ')
                    .strip())

            price_info = price_dict.get(product_id, {})
            sub_type = price_info.get('subTypeName', 'N/A')

            try:
                if '/' not in ext_num or ext_num == '':
                    if sub_type == 'Normal':
                        search_term = f'{name} {display_group} {ext_num}'.strip()
                    elif sub_type == 'Holofoil':
                        search_term = f'{name} {display_group} {ext_num} holo'.strip()
                    elif sub_type == 'Reverse Holofoil':
                        search_term = f'{name} {display_group} {ext_num} reverse holo'.strip()
                    else:
                        search_term = f'{name} {display_group} {ext_num}'.strip()
                elif display_group == 'Miscellaneous Cards & Products':
                    search_term = name
                elif sub_type == 'Normal':
                    search_term = f'{name} "{ext_num}" {display_group}'
                elif sub_type == 'Holofoil':
                    search_term = f'{name} "{ext_num}" {display_group} holo'
                elif sub_type == 'Reverse Holofoil':
                    search_term = f'{name} "{ext_num}" {display_group} reverse holo'
                else:
                    search_term = f'{name} "{ext_num}" {display_group}'
            except Exception:
                search_term = f'{product_name} {display_group}'

            search_term = _quote_special_terms(search_term)

            low_price = price_info.get('lowPrice')
            mid_price = price_info.get('midPrice')
            market_price = price_info.get('marketPrice')

            try:
                low_price_value = float(low_price) if low_price is not None else None
            except (ValueError, TypeError):
                low_price_value = None

            if min_price is not None and max_price is not None:
                if low_price_value is None or not (min_price <= low_price_value <= max_price):
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
