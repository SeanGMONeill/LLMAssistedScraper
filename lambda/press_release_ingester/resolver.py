"""
Production entity resolver (Named Entity Disambiguation).

Given LLM-extracted fields (show_name, show_type, production_label, theatre, city),
returns a stable production_id by:
  1. Normalising show_name → show_slug via shows_config aliases
  2. Querying DynamoDB SHOW#{slug}/PRODUCTION#* for existing productions
  3. Matching on theatre (residency), production_label fuzzy match (touring),
     or sole-production heuristic
  4. Generating a new production_id if no match found
"""

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Optional

from boto3.dynamodb.conditions import Key


# ---------------------------------------------------------------------------
# Show name normalisation
# ---------------------------------------------------------------------------

def slugify(text: str) -> str:
    """Lowercase, strip accents, collapse non-alphanumeric runs to hyphens."""
    text = text.strip().lower()
    text = ''.join(
        c for c in unicodedata.normalize('NFD', text)
        if unicodedata.category(c) != 'Mn'
    )
    text = re.sub(r'[^a-z0-9]+', '-', text)
    return text.strip('-')


def normalize_show_name(show_name: str, shows_config: list[dict]) -> tuple[str, str]:
    """
    Returns (show_slug, canonical_name).

    Checks shows_config aliases first; falls back to slugifying the raw name.
    """
    name_lower = show_name.strip().lower()
    for entry in shows_config:
        if name_lower == entry['canonical_name'].lower():
            return entry['show_slug'], entry['canonical_name']
        for alias in entry.get('aliases', []):
            if name_lower == alias.lower():
                return entry['show_slug'], entry['canonical_name']
    # Auto-slugify — canonical_name is whatever the LLM gave us
    return slugify(show_name), show_name.strip()


# ---------------------------------------------------------------------------
# DynamoDB lookup
# ---------------------------------------------------------------------------

def get_existing_productions(show_slug: str, show_index_table) -> list[dict]:
    """
    Query SHOW#{show_slug}/PRODUCTION#* items from the ShowIndex table.
    Returns a list of production summary dicts.
    """
    try:
        response = show_index_table.query(
            KeyConditionExpression=(
                Key('PK').eq(f"SHOW#{show_slug}") &
                Key('SK').begins_with('PRODUCTION#')
            )
        )
        return response.get('Items', [])
    except Exception as e:
        print(f"[resolver] Error querying productions for {show_slug}: {e}")
        return []


# ---------------------------------------------------------------------------
# Matching logic
# ---------------------------------------------------------------------------

def _normalize_theatre(name: str) -> str:
    """Strip common suffixes for fuzzy theatre comparison."""
    name = name.lower().strip()
    for suffix in (' theatre', ' playhouse', ' hall', ' centre', ' center', ' opera house'):
        if name.endswith(suffix):
            name = name[:-len(suffix)]
    return name.strip()


def _label_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def find_matching_production(
    existing: list[dict],
    show_type: Optional[str],
    production_label: Optional[str],
    theatre: Optional[str],
    city: Optional[str],
) -> Optional[dict]:
    """
    Try to match LLM-extracted metadata against existing production summary items.
    Returns the matching item dict, or None.
    """
    if not existing:
        return None

    # --- Theatre match (residency) — high confidence ---
    if theatre:
        norm_theatre = _normalize_theatre(theatre)
        for prod in existing:
            if prod.get('theatre') and _normalize_theatre(prod['theatre']) == norm_theatre:
                print(f"[resolver] Theatre match → {prod['production_id']}")
                return prod

    # --- Production label fuzzy match ---
    if production_label:
        best_score, best_prod = 0.0, None
        for prod in existing:
            if prod.get('production_label'):
                score = _label_similarity(production_label, prod['production_label'])
                if score > best_score:
                    best_score, best_prod = score, prod
        if best_score >= 0.80:
            print(f"[resolver] Label fuzzy match ({best_score:.2f}) → {best_prod['production_id']}")
            return best_prod

    # --- Sole-production heuristic — only one production exists for this show ---
    if len(existing) == 1:
        prod = existing[0]
        # Accept if show_type matches or is absent
        if not show_type or not prod.get('show_type') or show_type == prod.get('show_type'):
            print(f"[resolver] Sole-production heuristic → {prod['production_id']}")
            return prod

    return None


# ---------------------------------------------------------------------------
# Production ID generation
# ---------------------------------------------------------------------------

def generate_production_id(
    show_slug: str,
    show_type: Optional[str],
    production_label: Optional[str],
    theatre: Optional[str],
    article_year: Optional[str],
) -> str:
    """Generate a candidate production_id for a new, previously-unseen production."""
    if production_label:
        label_slug = slugify(production_label)
        return f"{show_slug}-{label_slug}"

    if theatre:
        # Simplify theatre name for ID — strip "Theatre", use first meaningful word(s)
        t = slugify(theatre)
        for stop in ('-theatre', '-playhouse', '-hall', '-centre', '-center'):
            if t.endswith(stop):
                t = t[:-len(stop)]
        return f"{show_slug}-{t.strip('-')}"

    if article_year:
        return f"{show_slug}-{article_year}"

    return show_slug  # last resort — will be flagged needs_review


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def resolve_production(
    show_name: str,
    show_type: Optional[str],
    production_label: Optional[str],
    theatre: Optional[str],
    city: Optional[str],
    article_date: Optional[str],
    show_index_table,
    shows_config: list[dict],
) -> tuple[str, str, str, bool]:
    """
    Resolve LLM-extracted show metadata to a stable production_id.

    Returns:
        (production_id, show_slug, canonical_name, is_new)
        is_new=True means this production was not previously known.
    """
    show_slug, canonical_name = normalize_show_name(show_name, shows_config)

    existing = get_existing_productions(show_slug, show_index_table)

    match = find_matching_production(existing, show_type, production_label, theatre, city)
    if match:
        return match['production_id'], show_slug, canonical_name, False

    # No match — generate new production_id
    article_year = article_date[:4] if article_date and len(article_date) >= 4 else None
    production_id = generate_production_id(show_slug, show_type, production_label, theatre, article_year)

    print(f"[resolver] New production: {production_id} (show_slug={show_slug})")
    return production_id, show_slug, canonical_name, True
