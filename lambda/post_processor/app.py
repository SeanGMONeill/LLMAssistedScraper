"""
Lambda function for post-processing scrape results.
Triggered by DynamoDB Streams, updates ActorIndex and ShowIndex tables.

DynamoDB key structure (production model):
  ShowIndex:
    SHOW#{show_slug}       / PRODUCTION#{production_id}  — production summary
    PRODUCTION#{prod_id}   / CURRENT                     — full current cast
    PRODUCTION#{prod_id}   / ACTOR#{actor}#{ts}          — actor history
  ActorIndex:
    ACTOR#{actor}          / PRODUCTION#{prod_id}#JOINED#{ts}
"""

import json
import os
import boto3
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from decimal import Decimal

# AWS clients
dynamodb = boto3.resource('dynamodb')
sns = boto3.client('sns')

# Environment variables
SCRAPES_TABLE = os.environ['SCRAPES_TABLE']
ACTOR_INDEX_TABLE = os.environ['ACTOR_INDEX_TABLE']
SHOW_INDEX_TABLE = os.environ['SHOW_INDEX_TABLE']
ALERT_TOPIC_ARN = os.environ['ALERT_TOPIC_ARN']
ENVIRONMENT = os.environ['ENVIRONMENT']


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _show_index():
    return dynamodb.Table(SHOW_INDEX_TABLE)

def _actor_index():
    return dynamodb.Table(ACTOR_INDEX_TABLE)

def _scrapes():
    return dynamodb.Table(SCRAPES_TABLE)


# ---------------------------------------------------------------------------
# Previous scrape lookup
# ---------------------------------------------------------------------------

def get_previous_scrape(production_id: str) -> Optional[Dict[str, Any]]:
    """Get the most recent previous scrape for a production."""
    from boto3.dynamodb.conditions import Key
    response = _scrapes().query(
        KeyConditionExpression=(
            Key('PK').eq(f"PRODUCTION#{production_id}") &
            Key('SK').begins_with('SCRAPE#')
        ),
        ScanIndexForward=False,  # newest first
        Limit=2
    )
    items = response.get('Items', [])
    return items[1] if len(items) > 1 else None


# ---------------------------------------------------------------------------
# Data quality validation (cast_list_page path only)
# ---------------------------------------------------------------------------

def validate_data_quality(new_scrape: Dict[str, Any], previous_scrape: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Validate data quality by comparing new scrape to previous.

    Returns:
        {
            "should_update_indexes": bool,
            "warnings": List[str],
            "changes": Dict
        }
    """
    warnings = []
    new_cast = new_scrape.get('cast', [])
    new_count = len(new_cast)

    if previous_scrape is None:
        return {
            "should_update_indexes": True,
            "warnings": ["First scrape for this production"],
            "changes": {"type": "initial", "new_count": new_count}
        }

    prev_cast = previous_scrape.get('cast', [])
    prev_count = len(prev_cast)

    # Suspicious drop
    if new_count < prev_count * 0.5:
        warnings.append(
            f"Cast count dropped significantly: {prev_count} → {new_count} "
            f"({(new_count / prev_count * 100):.0f}% of previous)"
        )
        return {
            "should_update_indexes": False,
            "warnings": warnings,
            "changes": {"type": "suspicious_drop", "prev_count": prev_count, "new_count": new_count}
        }

    # Complete replacement
    prev_actors = {m['actor'] for m in prev_cast if 'actor' in m}
    new_actors = {m['actor'] for m in new_cast if 'actor' in m}

    overlap = prev_actors & new_actors
    overlap_pct = len(overlap) / len(prev_actors) * 100 if prev_actors else 0

    if overlap_pct == 0 and prev_count > 5:
        warnings.append(
            f"Complete cast replacement detected (0% overlap). "
            f"Previous: {prev_count} actors, New: {new_count} actors"
        )
        return {
            "should_update_indexes": False,
            "warnings": warnings,
            "changes": {"type": "complete_replacement", "prev_count": prev_count, "new_count": new_count}
        }

    actors_joined = new_actors - prev_actors
    actors_left = prev_actors - new_actors

    return {
        "should_update_indexes": True,
        "warnings": warnings if warnings else None,
        "changes": {
            "type": "normal",
            "prev_count": prev_count,
            "new_count": new_count,
            "actors_joined": list(actors_joined),
            "actors_left": list(actors_left),
            "overlap_pct": round(overlap_pct, 1)
        }
    }


# ---------------------------------------------------------------------------
# ShowIndex writes — cast_list_page path
# ---------------------------------------------------------------------------

def update_show_index(scrape: Dict[str, Any]) -> None:
    """
    Update ShowIndex with:
      1. PRODUCTION#{prod_id}/CURRENT — full current cast (scrape is authoritative)
      2. SHOW#{show_slug}/PRODUCTION#{prod_id} — production summary
      3. PRODUCTION#{prod_id}/ACTOR#{actor}#{ts} — per-actor history
    """
    from boto3.dynamodb.conditions import Key
    table = _show_index()
    production_id = scrape['production_id']
    show_name = scrape['show_name']
    show_slug = scrape['show_slug']
    cast = scrape['cast']
    scraped_at = scrape['scraped_at']

    # 1. PRODUCTION# / CURRENT (includes show metadata for API convenience)
    current_item = {
        'PK': f"PRODUCTION#{production_id}",
        'SK': 'CURRENT',
        'cast': cast,
        'last_updated': scraped_at,
        'cast_count': len(cast),
        'data_source': 'scrape',
        'show_name': show_name,
        'show_slug': show_slug,
    }
    for field in ('production_label', 'show_type', 'theatre', 'city', 'production_company'):
        if scrape.get(field):
            current_item[field] = scrape[field]
    table.put_item(Item={k: v for k, v in current_item.items() if v is not None})

    # 2. SHOW# / PRODUCTION# summary
    summary = {
        'PK': f"SHOW#{show_slug}",
        'SK': f"PRODUCTION#{production_id}",
        'production_id': production_id,
        'show_name': show_name,
        'show_slug': show_slug,
        'cast_count': len(cast),
        'last_updated': scraped_at,
        'data_source': 'scrape',
    }
    for field in ('production_label', 'show_type', 'theatre', 'city', 'production_company'):
        if scrape.get(field):
            summary[field] = scrape[field]
    table.put_item(Item=summary)

    # 3. Per-actor history
    for member in cast:
        actor = member.get('actor')
        role = member.get('role')
        if not actor or not role:
            continue

        try:
            response = table.query(
                KeyConditionExpression=(
                    Key('PK').eq(f"PRODUCTION#{production_id}") &
                    Key('SK').begins_with(f"ACTOR#{actor}#")
                ),
                Limit=1
            )

            if response.get('Items'):
                existing = response['Items'][0]
                roles = existing.get('roles', [])
                if role not in roles:
                    roles.append(role)
                table.update_item(
                    Key={'PK': existing['PK'], 'SK': existing['SK']},
                    UpdateExpression='SET last_seen = :ls, roles = :roles, is_current = :cur',
                    ExpressionAttributeValues={
                        ':ls': scraped_at,
                        ':roles': roles,
                        ':cur': True
                    }
                )
            else:
                table.put_item(Item={
                    'PK': f"PRODUCTION#{production_id}",
                    'SK': f"ACTOR#{actor}#{scraped_at}",
                    'actor_name': actor,
                    'roles': [role],
                    'first_seen': scraped_at,
                    'last_seen': scraped_at,
                    'is_current': True,
                    'data_source': 'scrape'
                })

        except Exception as e:
            print(f"Error updating ShowIndex history for {actor}: {e}")


# ---------------------------------------------------------------------------
# ActorIndex writes — cast_list_page path
# ---------------------------------------------------------------------------

def update_actor_index(scrape: Dict[str, Any], previous_scrape: Optional[Dict[str, Any]]) -> None:
    """Update ActorIndex with actor-production relationships."""
    from boto3.dynamodb.conditions import Key
    table = _actor_index()
    production_id = scrape['production_id']
    show_name = scrape['show_name']
    show_slug = scrape['show_slug']
    cast = scrape['cast']
    scraped_at = scrape['scraped_at']

    current_actors = {m['actor']: m['role'] for m in cast if 'actor' in m and 'role' in m}

    previous_actors = set()
    if previous_scrape:
        previous_actors = {m['actor'] for m in previous_scrape.get('cast', []) if 'actor' in m}

    actors_left = previous_actors - set(current_actors.keys())

    # Update current actors
    for actor, role in current_actors.items():
        try:
            response = table.query(
                KeyConditionExpression=(
                    Key('PK').eq(f"ACTOR#{actor}") &
                    Key('SK').begins_with(f"PRODUCTION#{production_id}#")
                ),
                Limit=1
            )

            if response.get('Items'):
                existing = response['Items'][0]
                roles = existing.get('roles', [])
                if role not in roles:
                    roles.append(role)
                table.update_item(
                    Key={'PK': existing['PK'], 'SK': existing['SK']},
                    UpdateExpression=(
                        'SET last_seen = :ls, roles = :roles, '
                        'is_current = :cur, appearance_count = appearance_count + :inc'
                    ),
                    ExpressionAttributeValues={
                        ':ls': scraped_at,
                        ':roles': roles,
                        ':cur': Decimal(1),
                        ':inc': Decimal(1)
                    }
                )
            else:
                item = {
                    'PK': f"ACTOR#{actor}",
                    'SK': f"PRODUCTION#{production_id}#JOINED#{scraped_at}",
                    'actor_name': actor,
                    'show_name': show_name,
                    'show_slug': show_slug,
                    'production_id': production_id,
                    'roles': [role],
                    'first_seen': scraped_at,
                    'last_seen': scraped_at,
                    'is_current': Decimal(1),
                    'appearance_count': Decimal(1),
                    'data_source': 'scrape'
                }
                for field in ('production_label', 'show_type', 'theatre', 'city'):
                    if scrape.get(field):
                        item[field] = scrape[field]
                table.put_item(Item=item)

        except Exception as e:
            print(f"Error updating ActorIndex for {actor}: {e}")

    # Mark actors who left
    for actor in actors_left:
        try:
            response = table.query(
                KeyConditionExpression=(
                    Key('PK').eq(f"ACTOR#{actor}") &
                    Key('SK').begins_with(f"PRODUCTION#{production_id}#")
                ),
                Limit=1
            )
            if response.get('Items'):
                existing = response['Items'][0]
                table.update_item(
                    Key={'PK': existing['PK'], 'SK': existing['SK']},
                    UpdateExpression='SET is_current = :cur',
                    ExpressionAttributeValues={':cur': Decimal(0)}
                )
        except Exception as e:
            print(f"Error marking {actor} as not current: {e}")


# ---------------------------------------------------------------------------
# ShowIndex + ActorIndex writes — press_release path
# ---------------------------------------------------------------------------

def update_actor_index_from_press_release(scrape: Dict[str, Any]) -> None:
    """
    Update ActorIndex from a press-release scrape.

    - Uses article_date (not scraped_at) for first_seen / last_seen
    - Does NOT mark any other actors as is_current = 0
    """
    from boto3.dynamodb.conditions import Key
    table = _actor_index()
    production_id = scrape['production_id']
    show_name = scrape['show_name']
    show_slug = scrape.get('show_slug', '')
    cast = scrape.get('cast', [])
    article_date = scrape.get('article_date') or scrape['scraped_at']

    for member in cast:
        actor = member.get('actor')
        role = member.get('role')
        if not actor or not role:
            continue

        try:
            response = table.query(
                KeyConditionExpression=(
                    Key('PK').eq(f"ACTOR#{actor}") &
                    Key('SK').begins_with(f"PRODUCTION#{production_id}#")
                ),
                Limit=1
            )

            if response.get('Items'):
                existing = response['Items'][0]
                roles = existing.get('roles', [])
                if role not in roles:
                    roles.append(role)

                cur_last = existing.get('last_seen', '')
                new_last = article_date if article_date > cur_last else cur_last
                cur_first = existing.get('first_seen', article_date)
                new_first = article_date if article_date < cur_first else cur_first

                table.update_item(
                    Key={'PK': existing['PK'], 'SK': existing['SK']},
                    UpdateExpression='SET last_seen = :ls, first_seen = :fs, roles = :roles',
                    ExpressionAttributeValues={
                        ':ls': new_last,
                        ':fs': new_first,
                        ':roles': roles
                    }
                )
            else:
                item = {
                    'PK': f"ACTOR#{actor}",
                    'SK': f"PRODUCTION#{production_id}#JOINED#{article_date}",
                    'actor_name': actor,
                    'show_name': show_name,
                    'show_slug': show_slug,
                    'production_id': production_id,
                    'roles': [role],
                    'first_seen': article_date,
                    'last_seen': article_date,
                    'is_current': Decimal(0),
                    'appearance_count': Decimal(1),
                    'data_source': 'press_release'
                }
                for field in ('production_label', 'show_type', 'theatre', 'city'):
                    if scrape.get(field):
                        item[field] = scrape[field]
                table.put_item(Item=item)

        except Exception as e:
            print(f"Error updating ActorIndex (press release) for {actor}: {e}")


def update_show_index_from_press_release(scrape: Dict[str, Any]) -> None:
    """
    Update ShowIndex from a press-release scrape (non-partial casts only).

    - PRODUCTION#/CURRENT only if no scrape-sourced CURRENT exists
    - SHOW#/PRODUCTION# summary only if no scrape-sourced summary exists
    - Always adds ACTOR# history entries using article_date
    """
    from boto3.dynamodb.conditions import Key
    table = _show_index()
    production_id = scrape['production_id']
    show_name = scrape['show_name']
    show_slug = scrape.get('show_slug', '')
    cast = scrape.get('cast', [])
    article_date = scrape.get('article_date') or scrape['scraped_at']

    # --- PRODUCTION# / CURRENT ---
    try:
        resp = table.get_item(Key={'PK': f"PRODUCTION#{production_id}", 'SK': 'CURRENT'})
        existing_current = resp.get('Item')
    except Exception as e:
        print(f"Error reading CURRENT for {production_id}: {e}")
        existing_current = None

    if existing_current is None or existing_current.get('data_source') == 'press_release':
        current_item = {
            'PK': f"PRODUCTION#{production_id}",
            'SK': 'CURRENT',
            'cast': cast,
            'last_updated': article_date,
            'cast_count': len(cast),
            'data_source': 'press_release',
            'show_name': show_name,
            'show_slug': show_slug,
        }
        for field in ('production_label', 'show_type', 'theatre', 'city', 'production_company'):
            if scrape.get(field):
                current_item[field] = scrape[field]
        table.put_item(Item={k: v for k, v in current_item.items() if v is not None})

    # --- SHOW# / PRODUCTION# summary ---
    try:
        resp = table.get_item(Key={
            'PK': f"SHOW#{show_slug}",
            'SK': f"PRODUCTION#{production_id}"
        })
        existing_summary = resp.get('Item')
    except Exception as e:
        print(f"Error reading SHOW# summary for {production_id}: {e}")
        existing_summary = None

    if existing_summary is None or existing_summary.get('data_source') == 'press_release':
        summary = {
            'PK': f"SHOW#{show_slug}",
            'SK': f"PRODUCTION#{production_id}",
            'production_id': production_id,
            'show_name': show_name,
            'show_slug': show_slug,
            'cast_count': len(cast),
            'last_updated': article_date,
            'data_source': 'press_release',
        }
        for field in ('production_label', 'show_type', 'theatre', 'city', 'production_company'):
            if scrape.get(field):
                summary[field] = scrape[field]
        table.put_item(Item=summary)

    # --- Per-actor history ---
    for member in cast:
        actor = member.get('actor')
        role = member.get('role')
        if not actor or not role:
            continue

        try:
            response = table.query(
                KeyConditionExpression=(
                    Key('PK').eq(f"PRODUCTION#{production_id}") &
                    Key('SK').begins_with(f"ACTOR#{actor}#")
                ),
                Limit=1
            )

            if response.get('Items'):
                existing = response['Items'][0]
                roles = existing.get('roles', [])
                if role not in roles:
                    roles.append(role)

                cur_last = existing.get('last_seen', '')
                new_last = article_date if article_date > cur_last else cur_last
                table.update_item(
                    Key={'PK': existing['PK'], 'SK': existing['SK']},
                    UpdateExpression='SET last_seen = :ls, roles = :roles',
                    ExpressionAttributeValues={':ls': new_last, ':roles': roles}
                )
            else:
                table.put_item(Item={
                    'PK': f"PRODUCTION#{production_id}",
                    'SK': f"ACTOR#{actor}#{article_date}",
                    'actor_name': actor,
                    'roles': [role],
                    'first_seen': article_date,
                    'last_seen': article_date,
                    'is_current': False,
                    'data_source': 'press_release'
                })

        except Exception as e:
            print(f"Error updating ShowIndex history (press release) for {actor}: {e}")


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

def send_alert(subject: str, message: str) -> None:
    try:
        sns.publish(
            TopicArn=ALERT_TOPIC_ARN,
            Subject=f"[{ENVIRONMENT.upper()}] {subject}",
            Message=message
        )
        print(f"Sent alert: {subject}")
    except Exception as e:
        print(f"Failed to send alert: {e}")


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

def lambda_handler(event, context):
    """Lambda handler triggered by DynamoDB Streams."""
    print(f"Received {len(event['Records'])} DynamoDB stream records")

    for record in event['Records']:
        try:
            if record['eventName'] != 'INSERT':
                continue

            new_image = record['dynamodb']['NewImage']

            from boto3.dynamodb.types import TypeDeserializer
            deserializer = TypeDeserializer()
            scrape = {k: deserializer.deserialize(v) for k, v in new_image.items()}

            pk = scrape.get('PK', '')

            # Skip old-schema items (PK = SHOW#...) — handled by migration
            if not pk.startswith('PRODUCTION#'):
                print(f"Skipping old-schema item (PK={pk}) — awaiting migration")
                continue

            # Only process actual scrape records, not CURRENT / ACTOR# history writes
            sk = scrape.get('SK', '')
            if not sk.startswith('SCRAPE#'):
                continue

            production_id = scrape.get('production_id') or pk.removeprefix('PRODUCTION#')
            show_name = scrape.get('show_name', '')
            source_type = scrape.get('source_type', 'cast_list_page')
            is_partial = scrape.get('is_partial_cast', False)

            print(f"Processing scrape for {show_name} / {production_id} "
                  f"(source_type={source_type}, is_partial={is_partial})")

            if source_type == 'press_release':
                update_actor_index_from_press_release(scrape)
                if not is_partial:
                    update_show_index_from_press_release(scrape)
                print(f"Updated indexes from press release for {production_id}")

            else:
                # cast_list_page path — with data quality validation
                previous_scrape = get_previous_scrape(production_id)
                validation = validate_data_quality(scrape, previous_scrape)

                if not validation['should_update_indexes']:
                    send_alert(
                        f"Data Quality Issue: {show_name}",
                        f"Show: {show_name}\n"
                        f"Production: {production_id}\n"
                        f"Warnings: {', '.join(validation['warnings'])}\n"
                        f"Changes: {json.dumps(validation['changes'], indent=2)}\n"
                        f"Time: {scrape['scraped_at']}\n\n"
                        f"Indexes NOT updated — requires manual review."
                    )
                    print(f"Skipping index updates for {production_id} due to data quality issues")
                    continue

                update_show_index(scrape)
                update_actor_index(scrape, previous_scrape)
                print(f"Updated indexes for {production_id}")

                changes = validation['changes']
                if changes['type'] == 'normal' and (
                    len(changes.get('actors_joined', [])) > 3 or
                    len(changes.get('actors_left', [])) > 3
                ):
                    send_alert(
                        f"Significant Cast Changes: {show_name}",
                        f"Show: {show_name}\n"
                        f"Production: {production_id}\n"
                        f"Actors joined: {', '.join(changes.get('actors_joined', [])) or 'None'}\n"
                        f"Actors left: {', '.join(changes.get('actors_left', [])) or 'None'}\n"
                        f"Overlap: {changes.get('overlap_pct')}%\n"
                        f"Time: {scrape['scraped_at']}"
                    )

        except Exception as e:
            print(f"Error processing stream record: {e}")
            import traceback
            traceback.print_exc()

    return {
        "statusCode": 200,
        "body": json.dumps({"processed": len(event['Records'])})
    }
