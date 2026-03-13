"""
Lambda function triggered by EventBridge scheduler.
Loads productions configuration and sends scraping jobs to SQS.
"""

import json
import os
import boto3
from datetime import datetime, timezone
from typing import Dict, Any, List

# AWS clients
sqs = boto3.client('sqs')
s3 = boto3.client('s3')
sns = boto3.client('sns')

# Environment variables
QUEUE_URL = os.environ['QUEUE_URL']
SITES_CONFIG_S3_BUCKET = os.environ['SITES_CONFIG_S3_BUCKET']
SITES_CONFIG_S3_KEY = os.environ['SITES_CONFIG_S3_KEY']
ALERT_TOPIC_ARN = os.environ['ALERT_TOPIC_ARN']
ENVIRONMENT = os.environ['ENVIRONMENT']


def load_productions_config() -> Dict[str, Any]:
    """Load scrape configuration from S3."""
    try:
        response = s3.get_object(
            Bucket=SITES_CONFIG_S3_BUCKET,
            Key=SITES_CONFIG_S3_KEY
        )
        config = json.loads(response['Body'].read().decode('utf-8'))
        print(f"Loaded scrape config with {len(config.get('productions', []))} productions")
        return config

    except Exception as e:
        print(f"Error loading scrape config from S3: {e}")
        raise


def send_scrape_jobs(productions: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    Send scraping jobs to SQS.

    Returns:
        {"sent": count, "failed": count}
    """
    sent = 0
    failed = 0

    for prod in productions:
        try:
            message = {
                "production_id": prod['production_id'],
                "show_name": prod['show_name'],
                "show_slug": prod['show_slug'],
                "url": prod['scrape_url'],
                "selectors": prod.get('selectors', {}),
                "theatre": prod.get('theatre'),
                "city": prod.get('city'),
                "production_label": prod.get('production_label'),
                "show_type": prod.get('show_type'),
                "production_company": prod.get('production_company'),
            }

            sqs.send_message(
                QueueUrl=QUEUE_URL,
                MessageBody=json.dumps(message),
                MessageAttributes={
                    'show_name': {
                        'StringValue': prod['show_name'],
                        'DataType': 'String'
                    }
                }
            )

            sent += 1
            print(f"Queued scrape job for {prod['show_name']} ({prod['production_id']})")

        except Exception as e:
            print(f"Failed to queue job for {prod.get('show_name', '?')}: {e}")
            failed += 1

    return {"sent": sent, "failed": failed}


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
    """Lambda handler triggered by EventBridge scheduler."""
    print(f"Starting daily scrape job at {datetime.now(timezone.utc).isoformat()}")

    try:
        config = load_productions_config()
        productions = config.get('productions', [])

        if not productions:
            error_msg = "No productions found in configuration"
            print(error_msg)
            send_alert("Scrape Job Failed", error_msg)
            return {
                "statusCode": 400,
                "body": json.dumps({"error": error_msg})
            }

        enabled = [p for p in productions if p.get('enabled', True)]
        print(f"Enabled productions: {len(enabled)} / {len(productions)}")

        result = send_scrape_jobs(enabled)
        print(f"Queued {result['sent']} scrape jobs, {result['failed']} failed")

        if result['failed'] > 0:
            send_alert(
                "Scrape Job Queueing Issues",
                f"Successfully queued: {result['sent']}\n"
                f"Failed to queue: {result['failed']}\n"
                f"Enabled productions: {len(enabled)}\n"
                f"Time: {datetime.now(timezone.utc).isoformat()}"
            )

        return {
            "statusCode": 200,
            "body": json.dumps({
                "queued": result['sent'],
                "failed": result['failed'],
                "enabled_productions": len(enabled),
                "total_productions": len(productions),
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
        }

    except Exception as e:
        print(f"Error in schedule target: {e}")
        import traceback
        traceback.print_exc()

        send_alert(
            "Scrape Job Orchestration Failed",
            f"Error: {str(e)}\n"
            f"Traceback:\n{traceback.format_exc()}\n"
            f"Time: {datetime.now(timezone.utc).isoformat()}"
        )

        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
