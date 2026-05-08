import requests
import csv
import os

# Backlog
# Separate functions for each category
# Identify false positives where ROI is greater than some value, refine target over time
# Do data transformation in here or SQL
# Add card condition filter, maybe establish a rough relationship between NM and LP price
# Condition filter didn't work 11/8/2024

# In ebay search if search term has or tin? (verify tin isn't in other names) change the category

# Figure out the missing card numbers with letters in them, probably how I set it up to fix something else
# ^Temp solution is to add unquoted card number
# If handling case by case do SWSH 
# Regex XY#

# Try to make it so it doesn't conflate cards with tins
# Define success, currently roughly 1 - nohing, 2 maybe an auction or something low roi, 3 not sure, 4 one good deal, 5 multiple good deals

#
# Ideas
# Try to group ebay prices to identify potential groupings for condition (in combination with description)
# Same thing but to identify graded cards


def fetch_tcg_data(category_name, output_directory, min_price=None, max_price=None):
    # Map category names to their corresponding IDs
    categories = {
        'magic': '1',
        'yugioh': '2',
        'pokemon': '3',
        'lorcana': '72'
    }

    # Get the category ID based on the category name
    category_id = categories.get(category_name.lower())
    if not category_id:
        print(f"Category '{category_name}' not found.")
        return

    # Change to the specified output directory
    os.chdir(output_directory)

    # Fetch all groups for the specified category
    r = requests.get(f"https://tcgcsv.com/tcgplayer/{category_id}/groups")
    all_groups = r.json()['results']

    # Prepare list to collect all products and prices
    all_data = []

    # Loop through each group
    for group in all_groups:
        group_id = group['groupId']
        group_name = group['name']

        # Fetch products in the group
        r = requests.get(f"https://tcgcsv.com/tcgplayer/{category_id}/{group_id}/products")
        products = r.json()['results']

        # Fetch prices for products in the group
        r = requests.get(f"https://tcgcsv.com/tcgplayer/{category_id}/{group_id}/prices")
        prices = r.json()['results']

        # Create a dictionary to link productId to their price info for easy access
        price_dict = {price['productId']: price for price in prices}

        # Process product information and link it with prices
        for product in products:
            
            product_id = product['productId']
            product_name = product['name']
            clean_name = product['cleanName']
            
            ext_num = ''  # Initialize ext_num
            if 'extendedData' in product and product['extendedData']:
                for data in product['extendedData']:
                    if data['name'] == 'Number':
                        ext_num = data['value']
                        break

            #Expedition has names with numbers in parenthesis which we need to remove
            if group_name == "Expedition":
                startPos = name.find("(")
                endPos = name.find(")")
                if startPos != -1 and endPos != -1:
                    name = name[:startPos] + name[endPos+1:]
            
            #If the group name follows the format char: or char - remove through the colon/dash
            for group_name in [group_name]:
                if "-" in group_name:
                    group_name = group_name.split("-")[1].lstrip()
                elif ":" in group_name and group_name.index(":") < 7:
                    group_name = group_name.split(": ")[1].lstrip()
                else:
                    group_name = group_name
            
                name = product_name

                try:
                    if ext_num in name:
                        name = name.replace(ext_num, "")
                    if name.startswith(group_name):
                        name = name[len(group_name):].strip()
                    if " tin" in name.lower() or " box" in name.lower() or "booster" in name.lower():
                        name = "unopened " + name
                except:
                    pass

                name = name.replace("(", "").replace(")", "")
                name = name.replace("[", "").replace("]", "")
                name = name.replace (" - ", " ")
                name = name.replace("-", " ")
                name = name.replace("  ", " ")
                

            # Find the corresponding price info
            price_info = price_dict.get(product_id, {})

            sub_type_name = price_info.get('subTypeName', 'N/A')
            try:
                # checks if ext number doesn't have /
                if '/' not in ext_num or ext_num == '':
                    if sub_type_name == 'Normal':
                        search_term = name + ' ' + group_name + ' ' + ext_num #temp solution for the cards that need something to narrow it down
                    elif sub_type_name == 'Holofoil':
                        search_term = name + ' ' + group_name + ' ' + ext_num + ' holo'
                    elif sub_type_name == 'Reverse Holofoil':    
                        search_term = name + ' ' + group_name + ' ' + ext_num + ' reverse holo'
                elif group_name == "Miscellaneous Cards & Products":
                    search_term = name
                elif sub_type_name == 'Normal':
                    search_term = name + ' \"' + ext_num + '\" ' + group_name
                elif sub_type_name == 'Holofoil':
                    search_term = name + ' \"' + ext_num + '\" ' + group_name + ' holo'
                elif sub_type_name == 'Reverse Holofoil':
                    search_term = name + ' \"' + ext_num + '\" ' + group_name + ' reverse holo'
                else:
                    search_term = name + ' \"' + ext_num + '\" ' + group_name
            except:
                search_term = product_name + ' ' + group_name
            card_url = product['url']
            
            
            low_price = price_info.get('lowPrice', 'N/A')
            mid_price = price_info.get('midPrice', 'N/A')
            market_price = price_info.get('marketPrice', 'N/A')

            # Convert prices to floats
            try:
                low_price_value = float(low_price)
            except (ValueError, TypeError):
                low_price_value = None

            if min_price is not None and max_price is not None:
                if low_price_value is None or low_price_value < min_price or low_price_value > max_price:
                    continue

            # Collect all relevant data
            all_data.append({
                'productId': product_id,
                'group': group_name,
                'name': product_name,
                'ext_num': ext_num,
                'cleanName': clean_name,
                'searchTerm': search_term,
                'url': card_url,
                'subTypeName': sub_type_name,
                'lowPrice': low_price,
                'midPrice': mid_price,
                'marketPrice': market_price
            })

    # Write to CSV with a name that reflects the chosen category
    csv_filename = f'tcglist_{category_name.lower()}.csv'
    with open(csv_filename, 'w', newline='', encoding='utf-8') as file:
        fieldnames = ['productId', 'group', 'name', 'ext_num', 'cleanName', 'searchTerm', 'url', 'subTypeName', 'lowPrice', 'midPrice', 'marketPrice']
        writer = csv.DictWriter(file, fieldnames=fieldnames)

        writer.writeheader()

        # Write all rows
        writer.writerows(all_data)

    print(f"Data has been exported to {csv_filename}")

# Example usage:
if __name__ == "__main__":
    mydirectory = r"C:\Users\chrsh\Documents\01. Programming\06. TCG Arb"
    category_name = 'pokemon'  # Change this to 'magic', 'yugioh', 'pokemon' or 'lorcana' as needed
    fetch_tcg_data(category_name, mydirectory, min_price=18, max_price=1800)
    