"""
Read-only API Lambda for West End Theatre Cast Tracker.
Routes: GET /shows, GET /shows/{name}, GET /actors/{name}
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


def get_shows():
    """Scan ShowIndexTable for all CURRENT items (one per show)."""
    table = dynamodb.Table(SHOW_INDEX_TABLE)
    response = table.scan(FilterExpression=Attr('SK').eq('CURRENT'))
    items = response.get('Items', [])
    shows = [
        {
            'name': item['PK'].removeprefix('SHOW#'),
            'cast_count': int(item.get('cast_count', 0)),
            'last_updated': item.get('last_updated', ''),
        }
        for item in items
    ]
    shows.sort(key=lambda x: x['name'])
    return {'shows': shows}


def get_show(show_name):
    """Query ShowIndexTable for CURRENT + ACTOR# history items."""
    table = dynamodb.Table(SHOW_INDEX_TABLE)
    response = table.query(
        KeyConditionExpression=Key('PK').eq(f'SHOW#{show_name}')
    )
    items = response.get('Items', [])

    current = None
    history = []

    for item in items:
        sk = item['SK']
        if sk == 'CURRENT':
            current = {
                'cast': item.get('cast', []),
                'cast_count': int(item.get('cast_count', 0)),
                'last_updated': item.get('last_updated', ''),
            }
        elif sk.startswith('ACTOR#'):
            history.append({
                'actor_name': item.get('actor_name', ''),
                'roles': item.get('roles', []),
                'first_seen': item.get('first_seen', ''),
                'last_seen': item.get('last_seen', ''),
                'is_current': bool(item.get('is_current', False)),
            })

    if current is None:
        return None

    # Current actors first, then sorted by first_seen ascending
    history.sort(key=lambda x: (not x['is_current'], x.get('first_seen', '')))

    return {
        'name': show_name,
        **current,
        'history': history,
    }


def get_actor(actor_name):
    """Query ActorIndexTable for all shows an actor has appeared in."""
    table = dynamodb.Table(ACTOR_INDEX_TABLE)
    response = table.query(
        KeyConditionExpression=Key('PK').eq(f'ACTOR#{actor_name}')
    )
    items = response.get('Items', [])
    shows = [
        {
            'show_name': item.get('show_name', ''),
            'roles': item.get('roles', []),
            'first_seen': item.get('first_seen', ''),
            'last_seen': item.get('last_seen', ''),
            'is_current': bool(item.get('is_current', Decimal(0))),
        }
        for item in items
    ]
    shows.sort(key=lambda x: x.get('first_seen', ''), reverse=True)
    return {'name': actor_name, 'shows': shows}


def lambda_handler(event, context):
    path = event.get('rawPath', '/')

    # Strip /api prefix added by CloudFront routing
    if path.startswith('/api'):
        path = path[4:] or '/'

    parts = [unquote(p) for p in path.strip('/').split('/') if p]

    try:
        if parts == ['shows']:
            return respond(200, get_shows())

        if len(parts) == 2 and parts[0] == 'shows':
            result = get_show(parts[1])
            if result is None:
                return respond(404, {'error': 'Show not found'})
            return respond(200, result)

        if len(parts) == 2 and parts[0] == 'actors':
            return respond(200, get_actor(parts[1]))

        return respond(404, {'error': 'Not found'})

    except Exception as e:
        print(f'Error handling {path}: {e}')
        traceback.print_exc()
        return respond(500, {'error': 'Internal server error'})
