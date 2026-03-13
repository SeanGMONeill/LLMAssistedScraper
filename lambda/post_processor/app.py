"""
Lambda function for post-processing scrape results.
Triggered by DynamoDB Streams, updates ActorIndex and ShowIndex tables.
"""

import json
import os
import boto3
from datetime import datetime, timezone
from typing import Dict, Any, List, Set, Tuple
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


def get_previous_scrape(show_name: str) -> Dict[str, Any] | None:
    """Get the most recent previous scrape for a show."""
    table = dynamodb.Table(SCRAPES_TABLE)

    response = table.query(
        KeyConditionExpression='PK = :pk',
        ExpressionAttributeValues={
            ':pk': f"SHOW#{show_name}"
        },
        ScanIndexForward=False,  # Descending order (newest first)
        Limit=2  # Get 2 most recent (current + previous)
    )

    items = response.get('Items', [])

    # Return the second item (previous scrape), if it exists
    return items[1] if len(items) > 1 else None


def validate_data_quality(new_scrape: Dict[str, Any], previous_scrape: Dict[str, Any] | None) -> Dict[str, Any]:
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

    # If no previous scrape, always update
    if previous_scrape is None:
        return {
            "should_update_indexes": True,
            "warnings": ["First scrape for this show"],
            "changes": {"type": "initial", "new_count": new_count}
        }

    prev_cast = previous_scrape.get('cast', [])
    prev_count = len(prev_cast)

    # Check for suspicious drops
    if new_count < prev_count * 0.5:
        warnings.append(
            f"Cast count dropped significantly: {prev_count} → {new_count} "
            f"({(new_count / prev_count * 100):.0f}% of previous)"
        )
        return {
            "should_update_indexes": False,  # Don't update - likely scraper error
            "warnings": warnings,
            "changes": {"type": "suspicious_drop", "prev_count": prev_count, "new_count": new_count}
        }

    # Check for complete cast replacement (0% overlap)
    prev_actors = {member['actor'] for member in prev_cast if 'actor' in member}
    new_actors = {member['actor'] for member in new_cast if 'actor' in member}

    overlap = prev_actors & new_actors
    overlap_pct = len(overlap) / len(prev_actors) * 100 if prev_actors else 0

    if overlap_pct == 0 and prev_count > 5:
        warnings.append(
            f"Complete cast replacement detected (0% overlap). "
            f"Previous: {prev_count} actors, New: {new_count} actors"
        )
        return {
            "should_update_indexes": False,  # Needs manual review
            "warnings": warnings,
            "changes": {"type": "complete_replacement", "prev_count": prev_count, "new_count": new_count}
        }

    # Calculate changes
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


def update_show_index(scrape: Dict[str, Any]) -> None:
    """Update ShowIndex table with current cast and history."""
    table = dynamodb.Table(SHOW_INDEX_TABLE)
    show_name = scrape['show_name']
    cast = scrape['cast']
    scraped_at = scrape['scraped_at']

    # Update CURRENT cast
    table.put_item(
        Item={
            'PK': f"SHOW#{show_name}",
            'SK': 'CURRENT',
            'cast': cast,
            'last_updated': scraped_at,
            'cast_count': len(cast)
        }
    )

    # Add history entries for each actor
    for member in cast:
        actor = member.get('actor')
        role = member.get('role')

        if not actor or not role:
            continue

        # Check if this actor already exists in the show's history
        try:
            response = table.query(
                KeyConditionExpression='PK = :pk AND begins_with(SK, :sk)',
                ExpressionAttributeValues={
                    ':pk': f"SHOW#{show_name}",
                    ':sk': f"ACTOR#{actor}#"
                },
                Limit=1
            )

            if response.get('Items'):
                # Actor exists - update last_seen
                existing = response['Items'][0]
                roles = existing.get('roles', [])

                # Add new role if not already tracked
                if role not in roles:
                    roles.append(role)

                table.update_item(
                    Key={
                        'PK': existing['PK'],
                        'SK': existing['SK']
                    },
                    UpdateExpression='SET last_seen = :last_seen, roles = :roles, is_current = :current',
                    ExpressionAttributeValues={
                        ':last_seen': scraped_at,
                        ':roles': roles,
                        ':current': True
                    }
                )
            else:
                # New actor - create entry
                table.put_item(
                    Item={
                        'PK': f"SHOW#{show_name}",
                        'SK': f"ACTOR#{actor}#{scraped_at}",
                        'actor_name': actor,
                        'roles': [role],
                        'first_seen': scraped_at,
                        'last_seen': scraped_at,
                        'is_current': True
                    }
                )

        except Exception as e:
            print(f"Error updating ShowIndex for {actor}: {e}")


def update_actor_index(scrape: Dict[str, Any], previous_scrape: Dict[str, Any] | None) -> None:
    """Update ActorIndex table with actor-show relationships."""
    table = dynamodb.Table(ACTOR_INDEX_TABLE)
    show_name = scrape['show_name']
    cast = scrape['cast']
    scraped_at = scrape['scraped_at']

    current_actors = {member['actor']: member['role'] for member in cast if 'actor' in member and 'role' in member}

    # Get previous actors to detect who left
    previous_actors = set()
    if previous_scrape:
        previous_actors = {member['actor'] for member in previous_scrape.get('cast', []) if 'actor' in member}

    # Actors who left
    actors_left = previous_actors - set(current_actors.keys())

    # Update current actors
    for actor, role in current_actors.items():
        try:
            # Check if actor-show relationship exists
            response = table.query(
                KeyConditionExpression='PK = :pk AND begins_with(SK, :sk)',
                ExpressionAttributeValues={
                    ':pk': f"ACTOR#{actor}",
                    ':sk': f"SHOW#{show_name}#"
                },
                Limit=1
            )

            if response.get('Items'):
                # Relationship exists - update last_seen
                existing = response['Items'][0]
                roles = existing.get('roles', [])

                if role not in roles:
                    roles.append(role)

                table.update_item(
                    Key={
                        'PK': existing['PK'],
                        'SK': existing['SK']
                    },
                    UpdateExpression='SET last_seen = :last_seen, roles = :roles, is_current = :current, appearance_count = appearance_count + :inc',
                    ExpressionAttributeValues={
                        ':last_seen': scraped_at,
                        ':roles': roles,
                        ':current': Decimal(1),
                        ':inc': Decimal(1)
                    }
                )
            else:
                # New relationship - create entry
                table.put_item(
                    Item={
                        'PK': f"ACTOR#{actor}",
                        'SK': f"SHOW#{show_name}#JOINED#{scraped_at}",
                        'actor_name': actor,
                        'show_name': show_name,
                        'roles': [role],
                        'first_seen': scraped_at,
                        'last_seen': scraped_at,
                        'is_current': Decimal(1),
                        'appearance_count': Decimal(1)
                    }
                )

        except Exception as e:
            print(f"Error updating ActorIndex for {actor}: {e}")

    # Mark actors who left as no longer current
    for actor in actors_left:
        try:
            response = table.query(
                KeyConditionExpression='PK = :pk AND begins_with(SK, :sk)',
                ExpressionAttributeValues={
                    ':pk': f"ACTOR#{actor}",
                    ':sk': f"SHOW#{show_name}#"
                },
                Limit=1
            )

            if response.get('Items'):
                existing = response['Items'][0]
                table.update_item(
                    Key={
                        'PK': existing['PK'],
                        'SK': existing['SK']
                    },
                    UpdateExpression='SET is_current = :current',
                    ExpressionAttributeValues={
                        ':current': Decimal(0)
                    }
                )

        except Exception as e:
            print(f"Error marking {actor} as not current: {e}")


def send_alert(subject: str, message: str) -> None:
    """Send SNS alert."""
    try:
        sns.publish(
            TopicArn=ALERT_TOPIC_ARN,
            Subject=f"[{ENVIRONMENT.upper()}] {subject}",
            Message=message
        )
        print(f"Sent alert: {subject}")
    except Exception as e:
        print(f"Failed to send alert: {e}")


def lambda_handler(event, context):
    """
    Lambda handler triggered by DynamoDB Streams.

    Event contains INSERT records for new scrapes with status="success".
    """
    print(f"Received {len(event['Records'])} DynamoDB stream records")

    for record in event['Records']:
        try:
            # Only process INSERT events
            if record['eventName'] != 'INSERT':
                continue

            # Parse new scrape
            new_image = record['dynamodb']['NewImage']
            scrape = json.loads(json.dumps(new_image), parse_float=Decimal)

            # Convert DynamoDB format to regular dict
            from boto3.dynamodb.types import TypeDeserializer
            deserializer = TypeDeserializer()
            scrape = {k: deserializer.deserialize(v) for k, v in new_image.items()}

            show_name = scrape['show_name']
            print(f"Processing scrape for {show_name}")

            # Get previous scrape
            previous_scrape = get_previous_scrape(show_name)

            # Validate data quality
            validation = validate_data_quality(scrape, previous_scrape)

            if not validation['should_update_indexes']:
                # Send alert for suspicious data
                send_alert(
                    f"Data Quality Issue: {show_name}",
                    f"Show: {show_name}\n"
                    f"Warnings: {', '.join(validation['warnings'])}\n"
                    f"Changes: {json.dumps(validation['changes'], indent=2)}\n"
                    f"Time: {scrape['scraped_at']}\n\n"
                    f"Indexes NOT updated - requires manual review."
                )
                print(f"Skipping index updates for {show_name} due to data quality issues")
                continue

            # Update indexes
            update_show_index(scrape)
            update_actor_index(scrape, previous_scrape)

            print(f"Successfully updated indexes for {show_name}")

            # Send informational alert for significant changes
            changes = validation['changes']
            if changes['type'] == 'normal' and (changes.get('actors_joined') or changes.get('actors_left')):
                if len(changes.get('actors_joined', [])) > 3 or len(changes.get('actors_left', [])) > 3:
                    send_alert(
                        f"Significant Cast Changes: {show_name}",
                        f"Show: {show_name}\n"
                        f"Actors joined: {', '.join(changes.get('actors_joined', [])) or 'None'}\n"
                        f"Actors left: {', '.join(changes.get('actors_left', [])) or 'None'}\n"
                        f"Overlap: {changes.get('overlap_pct')}%\n"
                        f"Time: {scrape['scraped_at']}"
                    )

        except Exception as e:
            print(f"Error processing stream record: {e}")
            import traceback
            traceback.print_exc()
            # Don't re-raise - we don't want to block other records

    return {
        "statusCode": 200,
        "body": json.dumps({"processed": len(event['Records'])})
    }
