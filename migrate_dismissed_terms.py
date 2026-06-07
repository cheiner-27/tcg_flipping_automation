"""
One-time migration: add quotes around card numbers in old dismissed_cards entries.

Old format: Aggron 1/109 Ruby and Sapphire reverse holo
New format: Aggron "1/109" Ruby and Sapphire reverse holo

Rule: quote the LAST unquoted X/Y pattern in each search_term that has no
existing quotes.  Entries that already contain a quote are already in the
new format and are skipped.

Run once, then delete this file.
"""

import re
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))
import config

# Matches card numbers like 1/109, 064/113, ?/28, K/28, H25/H32
CARD_NUM = re.compile(r'(?<!")\b([?\w]+/[\w]+)\b(?!")')


def migrate_term(term: str) -> str | None:
    """Return the corrected term, or None if no change is needed."""
    if '"' in term:
        return None  # already new format
    matches = list(CARD_NUM.finditer(term))
    if not matches:
        return None  # no card number — nothing to do
    last = matches[-1]
    return term[:last.start()] + f'"{last.group()}"' + term[last.end():]


def run():
    if not config.SUPABASE_URL or not config.SUPABASE_KEY:
        print("ERROR: SUPABASE_URL / SUPABASE_KEY not set.")
        sys.exit(1)

    from supabase import create_client
    client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)

    # Fetch all dismissed cards
    all_rows = []
    page_size = 1000
    offset = 0
    while True:
        resp = (
            client.table(config.SUPABASE_DISMISSED_TABLE)
            .select('id,search_term')
            .range(offset, offset + page_size - 1)
            .execute()
        )
        batch = resp.data or []
        all_rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size

    print(f"Fetched {len(all_rows)} dismissed cards")

    to_update = []
    for row in all_rows:
        new_term = migrate_term(row['search_term'] or '')
        if new_term is not None:
            to_update.append({'id': row['id'], 'old': row['search_term'], 'new': new_term})

    print(f"Entries to update: {len(to_update)}  |  Entries unchanged: {len(all_rows) - len(to_update)}")

    if not to_update:
        print("Nothing to do.")
        return

    # Preview first 10
    print("\nFirst 10 changes:")
    for item in to_update[:10]:
        print(f"  OLD: {item['old']}")
        print(f"  NEW: {item['new']}")
        print()

    confirm = input(f"Apply {len(to_update)} updates to Supabase? [y/N] ").strip().lower()
    if confirm != 'y':
        print("Aborted.")
        return

    updated = 0
    errors = 0
    for item in to_update:
        try:
            client.table(config.SUPABASE_DISMISSED_TABLE) \
                .update({'search_term': item['new']}) \
                .eq('id', item['id']) \
                .execute()
            updated += 1
        except Exception as e:
            print(f"  ERROR updating {item['id']}: {e}")
            errors += 1

    print(f"\nDone: {updated} updated, {errors} errors.")


if __name__ == '__main__':
    run()
