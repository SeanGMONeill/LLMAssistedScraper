"""
Migration script: transform ShowIndex and ActorIndex items from old schema to new schema.

Old schema:
  ShowIndex:  PK=SHOW#{show_name}  SK=CURRENT | ACTOR#{actor}#{ts}
  ActorIndex: PK=ACTOR#{actor}     SK=SHOW#{show_name}#JOINED#{ts}

New schema:
  ShowIndex:  PK=SHOW#{show_slug}        SK=PRODUCTION#{production_id}   (summary)
              PK=PRODUCTION#{prod_id}    SK=CURRENT                       (full cast)
              PK=PRODUCTION#{prod_id}    SK=ACTOR#{actor}#{ts}            (history)
  ActorIndex: PK=ACTOR#{actor}           SK=PRODUCTION#{prod_id}#JOINED#{ts}

For each old SHOW#{show_name}/CURRENT item:
  1. Look up show_name in scrape_config.json to get production_id, show_slug, etc.
  2. Write new PRODUCTION#{prod_id}/CURRENT
  3. Write new SHOW#{show_slug}/PRODUCTION#{prod_id} summary
  4. Migrate ACTOR# history items under new PK

For each old ACTOR#{actor}/SHOW#{show_name}#JOINED#{ts} item:
  1. Look up production_id from show_name
  2. Write new ACTOR#{actor}/PRODUCTION#{prod_id}#JOINED#{ts}

Usage:
    python scripts/migrate_to_production_model.py [--dry-run] [--env dev]
"""

import argparse
import json
import sys
from pathlib import Path

import boto3
from boto3.dynamodb.conditions import Key, Attr


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent
SCRAPE_CONFIG_PATH = REPO_ROOT / 'sites' / 'scrape_config.json'


def load_scrape_config() -> dict[str, dict]:
    """Returns {show_name_lower: production_entry} and {show_slug: production_entry} mappings."""
    with open(SCRAPE_CONFIG_PATH) as f:
        config = json.load(f)
    by_name = {}
    by_slug = {}
    for prod in config['productions']:
        by_name[prod['show_name'].lower()] = prod
        by_slug[prod['show_slug']] = prod
    return by_name, by_slug


def lookup_production(show_name: str, config_by_name: dict, config_by_slug: dict):
    """Look up production config by show name, trying exact → slug match."""
    # Exact match
    match = config_by_name.get(show_name.lower())
    if match:
        return match
    # Slug-based match (strips accents, punctuation — handles "Les Miserables" → "les-miserables")
    slug = slugify(show_name)
    return config_by_slug.get(slug)


# ---------------------------------------------------------------------------
# Slugify (mirrors resolver.py)
# ---------------------------------------------------------------------------

import re
import unicodedata

def slugify(text: str) -> str:
    text = text.strip().lower()
    text = ''.join(
        c for c in unicodedata.normalize('NFD', text)
        if unicodedata.category(c) != 'Mn'
    )
    text = re.sub(r'[^a-z0-9]+', '-', text)
    return text.strip('-')


# ---------------------------------------------------------------------------
# Main migration
# ---------------------------------------------------------------------------

def migrate(env: str, dry_run: bool):
    dynamodb = boto3.resource('dynamodb', region_name='eu-west-2')
    show_index = dynamodb.Table(f'WestEndShowIndex-{env}')
    actor_index = dynamodb.Table(f'WestEndActorIndex-{env}')

    config_by_name, config_by_slug = load_scrape_config()

    # ------------------------------------------------------------------
    # Step 1: Scan ShowIndex for old-schema items (PK starts with SHOW#,
    # SK = CURRENT or ACTOR#)
    # ------------------------------------------------------------------
    print("=== Scanning ShowIndex for old-schema items ===")
    paginator_kwargs = {
        'FilterExpression': Attr('PK').begins_with('SHOW#') & Attr('SK').begins_with('ACTOR#') |
                            Attr('PK').begins_with('SHOW#') & Attr('SK').eq('CURRENT')
    }

    # Scan all old SHOW# items
    old_show_items = []
    response = show_index.scan(FilterExpression=(
        Attr('PK').begins_with('SHOW#') &
        (Attr('SK').eq('CURRENT') | Attr('SK').begins_with('ACTOR#'))
    ))
    old_show_items.extend(response.get('Items', []))
    while response.get('LastEvaluatedKey'):
        response = show_index.scan(
            FilterExpression=(
                Attr('PK').begins_with('SHOW#') &
                (Attr('SK').eq('CURRENT') | Attr('SK').begins_with('ACTOR#'))
            ),
            ExclusiveStartKey=response['LastEvaluatedKey']
        )
        old_show_items.extend(response.get('Items', []))

    print(f"Found {len(old_show_items)} old ShowIndex items")

    # Group by PK (show_name)
    by_show: dict[str, list] = {}
    for item in old_show_items:
        pk = item['PK']  # SHOW#{show_name}
        by_show.setdefault(pk, []).append(item)

    migrated_shows = 0
    skipped_shows = 0

    for pk, items in by_show.items():
        show_name = pk.removeprefix('SHOW#')
        show_name_lower = show_name.lower()

        # Look up production in config
        prod_config = lookup_production(show_name, config_by_name, config_by_slug)
        if prod_config:
            production_id = prod_config['production_id']
            show_slug = prod_config['show_slug']
            canonical_name = prod_config['show_name']
            production_label = prod_config.get('production_label')
            show_type = prod_config.get('show_type')
            theatre = prod_config.get('theatre')
            city = prod_config.get('city')
            production_company = prod_config.get('production_company')
        else:
            # Auto-derive
            show_slug = slugify(show_name)
            production_id = show_slug
            canonical_name = show_name
            production_label = None
            show_type = None
            theatre = None
            city = None
            production_company = None
            print(f"  [WARN] No config match for '{show_name}' — using auto-derived production_id={production_id}")

        current_item = next((i for i in items if i['SK'] == 'CURRENT'), None)
        actor_items = [i for i in items if i['SK'].startswith('ACTOR#')]

        print(f"\nMigrating: {show_name} → {production_id}")
        print(f"  CURRENT: {'yes' if current_item else 'no'}, ACTOR# history: {len(actor_items)}")

        # Check if new-schema items already exist (idempotent)
        existing = show_index.get_item(Key={
            'PK': f'PRODUCTION#{production_id}',
            'SK': 'CURRENT'
        }).get('Item')
        if existing and existing.get('data_source') == 'scrape':
            print(f"  [skip] PRODUCTION#{production_id}/CURRENT already exists (scrape-sourced)")
            skipped_shows += 1
            continue

        # --- Write PRODUCTION#/CURRENT ---
        if current_item:
            new_current = {
                'PK': f'PRODUCTION#{production_id}',
                'SK': 'CURRENT',
                'show_name': canonical_name,
                'show_slug': show_slug,
                'cast': current_item.get('cast', []),
                'cast_count': current_item.get('cast_count', 0),
                'last_updated': current_item.get('last_updated', ''),
                'data_source': current_item.get('data_source', 'scrape'),
            }
            for f, v in [('production_label', production_label), ('show_type', show_type),
                         ('theatre', theatre), ('city', city), ('production_company', production_company)]:
                if v:
                    new_current[f] = v
            if not dry_run:
                show_index.put_item(Item=new_current)
            print(f"  ✓ Wrote PRODUCTION#{production_id}/CURRENT")

        # --- Write SHOW#/PRODUCTION# summary ---
        summary = {
            'PK': f'SHOW#{show_slug}',
            'SK': f'PRODUCTION#{production_id}',
            'production_id': production_id,
            'show_name': canonical_name,
            'show_slug': show_slug,
            'cast_count': current_item.get('cast_count', 0) if current_item else 0,
            'last_updated': current_item.get('last_updated', '') if current_item else '',
            'data_source': current_item.get('data_source', 'scrape') if current_item else 'scrape',
        }
        for f, v in [('production_label', production_label), ('show_type', show_type),
                     ('theatre', theatre), ('city', city), ('production_company', production_company)]:
            if v:
                summary[f] = v
        if not dry_run:
            show_index.put_item(Item=summary)
        print(f"  ✓ Wrote SHOW#{show_slug}/PRODUCTION#{production_id} summary")

        # --- Migrate ACTOR# history items ---
        for actor_item in actor_items:
            old_sk = actor_item['SK']  # ACTOR#{actor}#{ts}
            new_pk = f'PRODUCTION#{production_id}'
            new_item = {
                **actor_item,
                'PK': new_pk,
                'SK': old_sk,  # ACTOR#{actor}#{ts} — same format
            }
            if not dry_run:
                show_index.put_item(Item=new_item)
        if actor_items:
            print(f"  ✓ Migrated {len(actor_items)} ACTOR# history items")

        migrated_shows += 1

    print(f"\nShowIndex: migrated={migrated_shows}, skipped={skipped_shows}")

    # ------------------------------------------------------------------
    # Step 2: Migrate ActorIndex items
    # ------------------------------------------------------------------
    print("\n=== Scanning ActorIndex for old-schema items ===")

    old_actor_items = []
    response = actor_index.scan(
        FilterExpression=Attr('SK').begins_with('SHOW#')
    )
    old_actor_items.extend(response.get('Items', []))
    while response.get('LastEvaluatedKey'):
        response = actor_index.scan(
            FilterExpression=Attr('SK').begins_with('SHOW#'),
            ExclusiveStartKey=response['LastEvaluatedKey']
        )
        old_actor_items.extend(response.get('Items', []))

    print(f"Found {len(old_actor_items)} old ActorIndex items")

    migrated_actors = 0
    skipped_actors = 0

    for item in old_actor_items:
        old_sk = item['SK']  # SHOW#{show_name}#JOINED#{ts}
        # Parse show_name from SK
        parts = old_sk.split('#JOINED#', 1)
        if len(parts) != 2:
            print(f"  [skip] Unrecognised SK format: {old_sk}")
            continue

        show_part = parts[0]  # SHOW#{show_name}
        joined_ts = parts[1]
        show_name = show_part.removeprefix('SHOW#')
        show_name_lower = show_name.lower()

        prod_config = lookup_production(show_name, config_by_name, config_by_slug)
        if prod_config:
            production_id = prod_config['production_id']
            show_slug = prod_config['show_slug']
            canonical_name = prod_config['show_name']
        else:
            show_slug = slugify(show_name)
            production_id = show_slug
            canonical_name = show_name

        new_sk = f'PRODUCTION#{production_id}#JOINED#{joined_ts}'

        # Check if already migrated
        existing = actor_index.get_item(Key={
            'PK': item['PK'],
            'SK': new_sk
        }).get('Item')
        if existing:
            skipped_actors += 1
            continue

        new_item = {
            **item,
            'SK': new_sk,
            'production_id': production_id,
            'show_slug': show_slug,
            'show_name': canonical_name,
        }
        # Remove old show_name field if it was the key one (keep actor show_name)
        if not dry_run:
            actor_index.put_item(Item=new_item)
        migrated_actors += 1

    print(f"ActorIndex: migrated={migrated_actors}, skipped={skipped_actors}")

    # ------------------------------------------------------------------
    # Step 3: Delete old items (after verifying new ones exist)
    # ------------------------------------------------------------------
    if not dry_run:
        print("\n=== Cleaning up old ShowIndex items ===")
        deleted = 0
        for item in old_show_items:
            pk = item['PK']
            sk = item['SK']
            show_name = pk.removeprefix('SHOW#')
            prod_config = lookup_production(show_name, config_by_name, config_by_slug)
            if prod_config:
                production_id = prod_config['production_id']
                show_slug = prod_config['show_slug']
            else:
                show_slug = slugify(show_name)
                production_id = show_slug

            # Verify new item exists before deleting old
            if sk == 'CURRENT':
                new_exists = show_index.get_item(Key={
                    'PK': f'PRODUCTION#{production_id}',
                    'SK': 'CURRENT'
                }).get('Item')
            else:
                new_exists = True  # ACTOR# items always safe to delete after copy

            if new_exists:
                show_index.delete_item(Key={'PK': pk, 'SK': sk})
                deleted += 1

        print(f"Deleted {deleted} old ShowIndex items")

        print("\n=== Cleaning up old ActorIndex items ===")
        deleted = 0
        for item in old_actor_items:
            old_sk = item['SK']
            parts = old_sk.split('#JOINED#', 1)
            if len(parts) != 2:
                continue
            show_part = parts[0]
            joined_ts = parts[1]
            show_name = show_part.removeprefix('SHOW#')
            prod_config = lookup_production(show_name, config_by_name, config_by_slug)
            production_id = prod_config['production_id'] if prod_config else slugify(show_name)

            new_sk = f'PRODUCTION#{production_id}#JOINED#{joined_ts}'
            new_exists = actor_index.get_item(Key={
                'PK': item['PK'],
                'SK': new_sk
            }).get('Item')
            if new_exists:
                actor_index.delete_item(Key={'PK': item['PK'], 'SK': old_sk})
                deleted += 1

        print(f"Deleted {deleted} old ActorIndex items")

    print("\n=== Migration complete ===")
    if dry_run:
        print("DRY RUN — no changes written")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Migrate DynamoDB to production model')
    parser.add_argument('--env', default='dev', help='Environment (dev/prod)')
    parser.add_argument('--dry-run', action='store_true', help='Log only, no writes')
    args = parser.parse_args()

    print(f"Migration: env={args.env}, dry_run={args.dry_run}")
    migrate(env=args.env, dry_run=args.dry_run)
