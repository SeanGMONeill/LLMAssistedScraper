"""
Lambda function for scraping West End theatre cast pages.
Triggered by SQS messages, writes results to DynamoDB.
"""

import json
import os
import boto3
from datetime import datetime, timezone
from typing import Dict, Any, List
import traceback

# Import scraping modules (copied into container)
from direct_extractor import DirectExtractor
from anthropic_client import AnthropicClient

# AWS clients
dynamodb = boto3.resource('dynamodb')
sns = boto3.client('sns')
secretsmanager = boto3.client('secretsmanager')

# Environment variables
SCRAPES_TABLE = os.environ['SCRAPES_TABLE']
ALERT_TOPIC_ARN = os.environ['ALERT_TOPIC_ARN']
ANTHROPIC_API_KEY_SECRET = os.environ['ANTHROPIC_API_KEY_SECRET']
ENVIRONMENT = os.environ['ENVIRONMENT']

# Version for debugging
SCRAPER_VERSION = '1.0.0'

# Cache API key
_anthropic_api_key = None

def get_anthropic_api_key() -> str:
    """Retrieve Anthropic API key from Secrets Manager (cached)."""
    global _anthropic_api_key

    if _anthropic_api_key is None:
        try:
            response = secretsmanager.get_secret_value(SecretId=ANTHROPIC_API_KEY_SECRET)
            _anthropic_api_key = response['SecretString']
        except Exception as e:
            print(f"Error retrieving API key from Secrets Manager: {e}")
            raise

    return _anthropic_api_key


def validate_scrape_result(cast: List[Dict[str, str]], show_name: str) -> Dict[str, Any]:
    """
    Validate scrape results before writing to DynamoDB.

    Returns:
        {
            "valid": bool,
            "errors": List[str],
            "warnings": List[str]
        }
    """
    errors = []
    warnings = []

    # Check: Cast count > 0
    if not cast or len(cast) == 0:
        errors.append("Cast list is empty")
        return {"valid": False, "errors": errors, "warnings": warnings}

    # Check: Each cast member has role AND actor
    for i, member in enumerate(cast):
        if not member.get('role'):
            errors.append(f"Cast member {i} missing 'role'")
        if not member.get('actor'):
            errors.append(f"Cast member {i} missing 'actor'")

    # Check: No duplicate role+actor combinations
    seen = set()
    for member in cast:
        key = (member.get('role', ''), member.get('actor', ''))
        if key in seen:
            warnings.append(f"Duplicate entry: {member.get('role')} - {member.get('actor')}")
        seen.add(key)

    # Check: Suspiciously small cast (< 3 for a typical West End show)
    if len(cast) < 3:
        warnings.append(f"Suspiciously small cast: {len(cast)} members")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings
    }


def scrape_show(job: Dict[str, Any]) -> Dict[str, Any]:
    """
    Scrape a single show's cast page.

    Args:
        job: {
            "production_id": str, "show_name": str, "show_slug": str,
            "url": str, "selectors": {...},
            "theatre": str, "city": str,
            "production_label": str, "show_type": str, "production_company": str
        }

    Returns:
        Scrape result dict ready for DynamoDB
    """
    production_id = job['production_id']
    show_name = job['show_name']
    show_slug = job['show_slug']
    url = job['url']
    selectors = job.get('selectors', {})
    theatre = job.get('theatre')
    city = job.get('city')
    production_label = job.get('production_label')
    show_type = job.get('show_type')
    production_company = job.get('production_company')

    print(f"Scraping {show_name} ({production_id}) from {url}")

    try:
        # Initialize scraper
        api_key = get_anthropic_api_key()
        extractor = DirectExtractor(url, selectors)
        client = AnthropicClient(api_key=api_key)

        # Scrape the page
        page_text = extractor.extract()
        print(f"Extracted {len(page_text)} characters from {url}")

        # Use LLM to parse cast information
        cast = client.extract_cast_info(page_text, show_name)
        print(f"Extracted {len(cast)} cast members")

        # Validate results
        validation = validate_scrape_result(cast, show_name)

        base_result = {
            "production_id": production_id,
            "show_name": show_name,
            "show_slug": show_slug,
            "source_url": url,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "theatre": theatre,
            "city": city,
            "production_label": production_label,
            "show_type": show_type,
            "production_company": production_company,
            "scraper_version": SCRAPER_VERSION,
        }

        if not validation['valid']:
            print(f"Validation failed: {validation['errors']}")
            return {
                **base_result,
                "scrape_status": "validation_failed",
                "error_msg": f"Validation errors: {', '.join(validation['errors'])}",
                "cast": cast,
                "cast_count": len(cast),
            }

        if validation['warnings']:
            print(f"Validation warnings: {validation['warnings']}")

        # Success!
        return {
            **base_result,
            "scrape_status": "success",
            "cast": cast,
            "cast_count": len(cast),
            "validation_warnings": validation['warnings'] if validation['warnings'] else None,
        }

    except Exception as e:
        print(f"Error scraping {show_name}: {e}")
        traceback.print_exc()

        return {
            "production_id": production_id,
            "show_name": show_name,
            "show_slug": show_slug,
            "source_url": url,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "scrape_status": "failed",
            "error_msg": str(e),
            "cast": [],
            "cast_count": 0,
            "theatre": theatre,
            "city": city,
            "production_label": production_label,
            "show_type": show_type,
            "production_company": production_company,
            "scraper_version": SCRAPER_VERSION,
        }


def write_to_dynamodb(result: Dict[str, Any]) -> None:
    """Write scrape result to DynamoDB."""
    table = dynamodb.Table(SCRAPES_TABLE)

    scraped_at = result['scraped_at']
    production_id = result['production_id']
    date_str = scraped_at.split('T')[0]  # YYYY-MM-DD

    item = {
        'PK': f"PRODUCTION#{production_id}",
        'SK': f"SCRAPE#{scraped_at}",
        'date_key': f"DATE#{date_str}",
        'source_type': 'cast_list_page',
        **result
    }

    # Remove None values
    item = {k: v for k, v in item.items() if v is not None}

    table.put_item(Item=item)
    print(f"Wrote scrape result to DynamoDB: {item['PK']} / {item['SK']}")


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
    Lambda handler triggered by SQS.

    Event structure:
    {
        "Records": [
            {
                "body": "{\"show_name\": \"Hamilton\", \"url\": \"...\", \"selectors\": {...}}"
            }
        ]
    }
    """
    print(f"Received {len(event['Records'])} SQS messages")

    results = []

    for record in event['Records']:
        try:
            # Parse SQS message
            job = json.loads(record['body'])
            show_name = job['show_name']

            # Scrape the show
            result = scrape_show(job)

            # Write to DynamoDB
            write_to_dynamodb(result)

            # Send alerts if needed
            if result['scrape_status'] == 'failed':
                send_alert(
                    f"Scrape Failed: {show_name}",
                    f"Show: {show_name}\n"
                    f"URL: {result['source_url']}\n"
                    f"Error: {result['error_msg']}\n"
                    f"Time: {result['scraped_at']}"
                )
            elif result['scrape_status'] == 'validation_failed':
                send_alert(
                    f"Validation Failed: {show_name}",
                    f"Show: {show_name}\n"
                    f"URL: {result['source_url']}\n"
                    f"Errors: {result['error_msg']}\n"
                    f"Cast count: {result['cast_count']}\n"
                    f"Time: {result['scraped_at']}"
                )

            results.append({
                "show_name": show_name,
                "status": result['scrape_status'],
                "cast_count": result['cast_count']
            })

        except Exception as e:
            print(f"Error processing record: {e}")
            traceback.print_exc()

            # Re-raise to send message to DLQ
            raise

    return {
        "statusCode": 200,
        "body": json.dumps({
            "processed": len(results),
            "results": results
        })
    }
