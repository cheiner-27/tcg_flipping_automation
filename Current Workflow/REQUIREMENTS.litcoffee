1. The TCGCSV API is called with tcgcsv_scraper_pokemon to get the most up to date pricing information from TCGPlayer. I specify the price range I'm looking for. 
2. The results are tcglist_pokemon.csv
3. The results are transformed in a few ways ahead of calling the ebay API. Full details are in tcgcsv_filtering
    3.1. It removes some groups and some types of products that I have found never have profitable opportunities
    3.2. It merges the query with the 'dismissed' cards I have exported from my tool. These are cards that are extremely low volume so I will never want to purchase. Because the way that tool was set up it has to perform a fuzzy match as the title of the search term is not formatted in the same way. If you read dismissed_cards_rows you may be able to identify a regex pattern to format it so the fuzzy match is needed. Otherwise, it is fine to leave as a fuzzy match.
    3.3. The results are saved as tcglist_pokemon_filtered.csv
4. This csv is fed to ebayApiPages to perform the searching
    4.1. It is worth noting here that everything is currently set up for just pokemon cards; however, eventually I plan on making adjustments to handle other TCGs.
5. The results of hitting the API are saved in pokemon_results_nm_only.csv
6. The results are transformed with full details available in final_result_generation
    6.1. Merges the results with the TCGCSV results for price comparison
    6.2. Filters to remove terms I don't want from the title such as things indicating the card is grading or is damaged and mislabeled as ungraded or near mint accordingly.
    6.3. Transforms the time remaining in the auction so that we can filter to only cards with 1 day remaining though this should be 2 I think.
    6.4. Performs checks to see if certain phrases appear in the search term they need to appear in the title e.g. SM201 in the search should have SM201 in the title. 
7. The results are saved as a csv, most recent being 20260320_NM_Pkmn_Results_Excel.csv