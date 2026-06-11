import os

EBAY_CLIENT_ID = os.environ.get('EBAY_CLIENT_ID', '')
EBAY_CLIENT_SECRET = os.environ.get('EBAY_CLIENT_SECRET', '')

SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '')
SUPABASE_DISMISSED_TABLE = os.environ.get('SUPABASE_DISMISSED_TABLE', 'dismissed_cards')
SUPABASE_DISMISSED_LISTINGS_TABLE = os.environ.get('SUPABASE_DISMISSED_LISTINGS_TABLE', 'dismissed_listings')

TCG_CATEGORY = os.environ.get('TCG_CATEGORY', 'pokemon')

POKEMON_MIN_PRICE = float(os.environ.get('POKEMON_MIN_PRICE', '15'))
POKEMON_MAX_PRICE = float(os.environ.get('POKEMON_MAX_PRICE', '2000'))
MAGIC_MIN_PRICE   = float(os.environ.get('MAGIC_MIN_PRICE', '35'))
MAGIC_MAX_PRICE   = float(os.environ.get('MAGIC_MAX_PRICE', '1000'))

BUYER_COUNTRY = os.environ.get('BUYER_COUNTRY', 'US')
BUYER_ZIP = os.environ.get('BUYER_ZIP', '21015')

MAX_AUCTION_DAYS = int(os.environ.get('MAX_AUCTION_DAYS', '2'))
MIN_ROI = float(os.environ.get('MIN_ROI', '0.07'))
