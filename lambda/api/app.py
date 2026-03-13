"""
Read-only API Lambda for West End Theatre Cast Tracker.

Routes:
  GET /shows                              — list all productions
  GET /shows/{show_slug}                  — list productions for a show
  GET /shows/{show_slug}/{production_id}  — production detail (cast + history)
  GET /actors/{actor_name}               — actor's production history
"""

import json
import os
import traceback
from decimal import Decimal
from urllib.parse import unquote

import boto3
from boto3.dynamodb.conditions import Key, Attr

dynamodb = boto3.resource('dynamodb')

ACTOR_INDEX_TABLE = os.environ['ACTOR_INDEX_TABLE']
SHOW_INDEX_TABLE = os.environ['SHOW_INDEX_TABLE']


class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return int(obj) if obj % 1 == 0 else float(obj)
        return super().default(obj)


def respond(status_code, body):
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
        },
        'body': json.dumps(body, cls=DecimalEncoder),
    }


def _production_summary(item: dict) -> dict:
    """Extract production summary fields from a SHOW#/PRODUCTION# item."""
    return {
        'production_id': item.get('production_id', item['SK'].removeprefix('PRODUCTION#')),
        'show_name': item.get('show_name', ''),
        'show_slug': item.get('show_slug', item['PK'].removeprefix('SHOW#')),
        'production_label': item.get('production_label') or '',
        'show_type': item.get('show_type') or '',
        'theatre': item.get('theatre') or '',
        'city': item.get('city') or '',
        'production_company': item.get('production_company') or '',
        'cast_count': int(item.get('cast_count', 0)),
        'last_updated': item.get('last_updated', ''),
        'data_source': item.get('data_source', 'scrape'),
    }


def get_shows():
    """
    Scan ShowIndex for all SHOW#/PRODUCTION# summary items.
    Returns one entry per production.
    """
    table = dynamodb.Table(SHOW_INDEX_TABLE)
    response = table.scan(
        FilterExpression=Attr('SK').begins_with('PRODUCTION#') & Attr('PK').begins_with('SHOW#')
    )
    items = response.get('Items', [])
    productions = [_production_summary(item) for item in items]
    productions.sort(key=lambda x: (x['show_name'], x['production_label']))
    return {'productions': productions}


def get_show(show_slug: str):
    """
    Query ShowIndex for all PRODUCTION# items under SHOW#{show_slug}.
    Returns list of production summaries.
    """
    table = dynamodb.Table(SHOW_INDEX_TABLE)
    response = table.query(
        KeyConditionExpression=(
            Key('PK').eq(f'SHOW#{show_slug}') &
            Key('SK').begins_with('PRODUCTION#')
        )
    )
    items = response.get('Items', [])
    if not items:
        return None

    productions = [_production_summary(item) for item in items]
    productions.sort(key=lambda x: x.get('production_label', ''))
    return {'show_slug': show_slug, 'productions': productions}


def get_production(production_id: str):
    """
    Query ShowIndex for PRODUCTION#{production_id}: CURRENT + ACTOR# history.
    """
    table = dynamodb.Table(SHOW_INDEX_TABLE)
    response = table.query(
        KeyConditionExpression=Key('PK').eq(f'PRODUCTION#{production_id}')
    )
    items = response.get('Items', [])

    current = None
    history = []

    for item in items:
        sk = item['SK']
        if sk == 'CURRENT':
            current = {
                'show_name': item.get('show_name', ''),
                'show_slug': item.get('show_slug', ''),
                'production_label': item.get('production_label') or '',
                'show_type': item.get('show_type') or '',
                'theatre': item.get('theatre') or '',
                'city': item.get('city') or '',
                'production_company': item.get('production_company') or '',
                'cast': item.get('cast', []),
                'cast_count': int(item.get('cast_count', 0)),
                'last_updated': item.get('last_updated', ''),
                'data_source': item.get('data_source', 'scrape'),
            }
        elif sk.startswith('ACTOR#'):
            history.append({
                'actor_name': item.get('actor_name', ''),
                'roles': item.get('roles', []),
                'first_seen': item.get('first_seen', ''),
                'last_seen': item.get('last_seen', ''),
                'is_current': bool(item.get('is_current', False)),
                'data_source': item.get('data_source', 'scrape'),
            })

    if current is None:
        return None

    history.sort(key=lambda x: (not x['is_current'], x.get('first_seen', '')))

    return {
        'production_id': production_id,
        **current,
        'history': history,
    }


def get_actor(actor_name: str):
    """Query ActorIndex for all productions an actor has appeared in."""
    table = dynamodb.Table(ACTOR_INDEX_TABLE)
    response = table.query(
        KeyConditionExpression=Key('PK').eq(f'ACTOR#{actor_name}')
    )
    items = response.get('Items', [])
    productions = [
        {
            'production_id': item.get('production_id', ''),
            'show_name': item.get('show_name', ''),
            'show_slug': item.get('show_slug', ''),
            'production_label': item.get('production_label', ''),
            'theatre': item.get('theatre', ''),
            'city': item.get('city', ''),
            'roles': item.get('roles', []),
            'first_seen': item.get('first_seen', ''),
            'last_seen': item.get('last_seen', ''),
            'is_current': bool(item.get('is_current', Decimal(0))),
        }
        for item in items
    ]
    productions.sort(key=lambda x: x.get('first_seen', ''), reverse=True)
    return {'name': actor_name, 'productions': productions}


def lambda_handler(event, context):
    path = event.get('rawPath', '/')

    # Strip /api prefix added by CloudFront routing
    if path.startswith('/api'):
        path = path[4:] or '/'

    parts = [unquote(p) for p in path.strip('/').split('/') if p]

    try:
        # GET /shows
        if parts == ['shows']:
            return respond(200, get_shows())

        # GET /shows/{show_slug}
        if len(parts) == 2 and parts[0] == 'shows':
            result = get_show(parts[1])
            if result is None:
                return respond(404, {'error': 'Show not found'})
            return respond(200, result)

        # GET /shows/{show_slug}/{production_id}
        if len(parts) == 3 and parts[0] == 'shows':
            result = get_production(parts[2])
            if result is None:
                return respond(404, {'error': 'Production not found'})
            return respond(200, result)

        # GET /actors/{actor_name}
        if len(parts) == 2 and parts[0] == 'actors':
            return respond(200, get_actor(parts[1]))

        return respond(404, {'error': 'Not found'})

    except Exception as e:
        print(f'Error handling {path}: {e}')
        traceback.print_exc()
        return respond(500, {'error': 'Internal server error'})
