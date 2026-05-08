from fastapi import params
import requests
import csv
import os
from bs4 import BeautifulSoup
from datetime import datetime, timezone
import base64
from urllib.parse import quote

mydirectory = r"C:\Users\chrsh\Documents\01. Programming\06. TCG Arb"
os.chdir(mydirectory)

BUYER_COUNTRY = "US"
BUYER_ZIP = "21015"

def get_oauth_token(client_id, client_secret):
    # Encode the client ID and client secret
    credentials = f'{client_id}:{client_secret}'
    encoded_credentials = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')

    # Set up headers and data for the token request
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Authorization': f'Basic {encoded_credentials}',
    }

    # Request scopes needed for the Browse API
    data = {
        'grant_type': 'client_credentials',
        'scope': 'https://api.ebay.com/oauth/api_scope',
    }

    # Make the request to get the OAuth token
    response = requests.post('https://api.ebay.com/identity/v1/oauth2/token', headers=headers, data=data)

    if response.status_code != 200:
        print(f"Error obtaining OAuth token: {response.status_code} - {response.text}")
        return None

    token_response = response.json()
    oauth_token = token_response.get('access_token')
    return oauth_token

def build_enduserctx(country=BUYER_COUNTRY, zip_code=BUYER_ZIP):
    # eBay requires the contextualLocation value to be URL-encoded.
    # Example final header value:
    #   "contextualLocation=country%3DUS%2Czip%3D21015"
    return f"contextualLocation={quote(f'country={country},zip={zip_code}', safe='')}"

def is_singles_term(term: str) -> bool:
    """
    Use singles category (183454) by default.
    Only NOT singles if:
      - term contains 'unopened', 'booster', 'box', 'case', 'deck', 'sealed'
      - term contains 'pack' AND has NO double quote (")
    """
    t = term.lower()
    non_singles_keywords = ["unopened", "booster", "box", "case", "deck", "sealed"]
    if any(keyword in t for keyword in non_singles_keywords):
        return False
    if "pack" in t and ('"' not in term):
        return False
    return True

def get_item_details(item_id, oauth_token):
    headers = {
    'Authorization': f'Bearer {oauth_token}',
    'Content-Type': 'application/json',
    'X-EBAY-C-MARKETPLACE-ID': 'EBAY_US',
    'X-EBAY-C-ENDUSERCTX': build_enduserctx(),  # <- add this
    }


    response = requests.get(
        f'https://api.ebay.com/buy/browse/v1/item/{item_id}',
        headers=headers
    )

    if response.status_code != 200:
        print(f"Error retrieving item details for {item_id}: {response.status_code} - {response.text}")
        return '', {}

    item_data = response.json()
    description_html = item_data.get('description', '')
    item_specifics = item_data.get('localizedAspects', [])

    # Handle HTML in item description
    soup = BeautifulSoup(description_html, 'html.parser')
    description = soup.get_text(separator=' ', strip=True)

    # Convert item specifics list to a dictionary
    specifics_dict = {aspect['name']: aspect['value'] for aspect in item_specifics}

    return description, specifics_dict

def get_item_details_raw(item_id, oauth_token):
    headers = {
    'Authorization': f'Bearer {oauth_token}',
    'Content-Type': 'application/json',
    'X-EBAY-C-MARKETPLACE-ID': 'EBAY_US',
    'X-EBAY-C-ENDUSERCTX': build_enduserctx(),
    }


    response = requests.get(
        f'https://api.ebay.com/buy/browse/v1/item/{item_id}',
        headers=headers
    )

    if response.status_code != 200:
        print(f"Error retrieving item details for {item_id}: {response.status_code} - {response.text}")
        return {}

    item_data = response.json()
    return item_data

def search_ebay_active_listings(search_term, oauth_token):
    headers = {
        'Authorization': f'Bearer {oauth_token}',
        'Content-Type': 'application/json',
        'X-EBAY-C-MARKETPLACE-ID': 'EBAY_US',
        'X-EBAY-C-ENDUSERCTX': build_enduserctx(),   # <-- important
    }

    singles = is_singles_term(search_term)

    # add deliveryCountry + deliveryPostalCode so eBay knows where to estimate to
    base_filter = 'buyingOptions:{AUCTION|FIXED_PRICE}'
    base_filter += f',deliveryCountry:{BUYER_COUNTRY},deliveryPostalCode:{BUYER_ZIP}'

    params = {
        'q': search_term,
        'limit': '200',
        'fieldgroups': 'EXTENDED,ASPECT_REFINEMENTS',
        'filter': base_filter,
    }
    if singles:
        params['category_ids'] = '183454'
        # Correct aspect_filter syntax: categoryId:ID,AspectName:{Value1|Value2}
        # Think we need to add another one to handle shit like Condition: Ungraded - Heavily Played
        params['aspect_filter'] = (
            'categoryId:183454,'
            'Card Condition:{Near Mint or Better},'
            'Graded:{No},'
            'Language:{English}'
        )

    def extract_shipping_cost_from_options(opts):
        best = None
        for opt in opts or []:
            # skip pure pickup options
            if (opt.get('type') or '').upper() == 'PICKUP':
                continue
            sc = opt.get('shippingCost')
            if sc and sc.get('value') is not None:
                try:
                    v = float(sc['value'])
                except (TypeError, ValueError):
                    continue
                best = v if best is None else min(best, v)
        return best  # None if nothing priced

    results = []
    offset = 0
    limit = 200
    params['limit'] = str(limit)

    while True:
        params['offset'] = str(offset)
        r = requests.get('https://api.ebay.com/buy/browse/v1/item_summary/search',
                         headers=headers, params=params)
        if r.status_code != 200:
            print(f"Error during eBay API request: {r.status_code} - {r.text}")
            break

        data = r.json()
        item_summaries = data.get('itemSummaries', []) or []
        
        if not item_summaries:
            break

        needs_detail_ids = []

        for item in item_summaries:
            item_id = item.get('itemId', '')
            title = item.get('title', '')
            price_info = item.get('price') or {}
            price = price_info.get('value')
            currency = price_info.get('currency', '')

            bid_info = item.get('currentBidPrice') or {}
            bidprice = bid_info.get('value')

            buying_options = item.get('buyingOptions') or []
            desc = item.get('shortDescription') or ''
            url = item.get('itemWebUrl', '')

            # try to read an estimated shipping price from search (may be missing for CALCULATED)
            shipping_cost = extract_shipping_cost_from_options(item.get('shippingOptions'))

            # If search didn't return a priced option, we'll fill it from getItem(s)
            if shipping_cost is None:
                needs_detail_ids.append(item_id)

            # card condition shortcut if present
            card_condition = ''
            for d in item.get("conditionDescriptors") or []:
                if (d.get("name") or "").strip().lower() == "card condition":
                    vs = d.get("values") or []
                    if vs:
                        card_condition = vs[0].get("content", "") or ""
                    break

            auction_price = buy_it_now_price = None
            if 'AUCTION' in buying_options:
                auction_price = bidprice or price
                if 'FIXED_PRICE' in buying_options:
                    buy_it_now_price = price
            elif 'FIXED_PRICE' in buying_options:
                buy_it_now_price = price

            results.append({
                'search_term': search_term,
                'status': 'active',
                'item_id': item_id,
                'title': title,
                'auction_price': auction_price,
                'buy_it_now_price': buy_it_now_price,
                'shipping_cost': shipping_cost,  # may be None (to be filled)
                'currency': currency,
                'time_remaining': None,  # left as-is, you can keep your original logic
                'url': url,
                'description': desc,
                'card_condition': card_condition
            })

        if 'next' not in data:
            break
            
        offset += limit
        
        # eBay API typically limits the maximum offset to 10,000
        if offset >= 10000:
            print(f"Reached 10,000 items limit for '{search_term}'.")
            break

    return results


def main():
    client_id = 'Christop-Thingwit-PRD-54fb4e75e-18572ff8'       # Replace with your eBay App ID (Client ID)
    client_secret = 'PRD-4fb4e75ec73f-5eb1-4eaf-b344-2cd9'
    oauth_token = get_oauth_token(client_id, client_secret)
    
    if not oauth_token:
        print("Failed to obtain OAuth token.")
        return
    
    # Read the CSV file containing search terms
    search_terms = []

    input_file = 'tcglist_pokemon_filtered.csv' 
    base_name = os.path.basename(input_file)
    name_key = base_name.split('_')[1].split('.')[0]
    output_file = f'{name_key}_results_nm_only.csv'

    with open(input_file, 'r', newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            term = row.get('searchTerm', '').strip()
            if term:
                search_terms.append(term)

    if not search_terms:
        print("No search terms found in the CSV file.")
        return

    category_ids = ['183454']

    # Initialize an empty list to hold all results
    all_results = []

    for search_term in search_terms:
        print(f"Searching for: {search_term}")
        active_results = search_ebay_active_listings(search_term, oauth_token)
        all_results.extend(active_results)


    # Now, write all accumulated results to the CSV file
    with open(output_file, 'w', newline='', encoding='utf-8') as file:
        fieldnames = ['search_term', 'status', 'item_id', 'title', 'auction_price', 'buy_it_now_price', 'shipping_cost', 'currency', 'time_remaining', 'url', 'description', 'card_condition']
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_results)
    # Print a success message
    print(f"Results saved to {output_file}")
if __name__ == '__main__':
    main()