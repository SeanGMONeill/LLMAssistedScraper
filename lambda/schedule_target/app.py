"""
Lambda function triggered by EventBridge scheduler.
Loads sites configuration and sends scraping jobs to SQS.
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


def load_sites_config() -> Dict[str, Any]:
    """Load sites configuration from S3."""
    try:
        response = s3.get_object(
            Bucket=SITES_CONFIG_S3_BUCKET,
            Key=SITES_CONFIG_S3_KEY
        )
        config = json.loads(response['Body'].read().decode('utf-8'))
        print(f"Loaded sites config with {len(config.get('sites', []))} sites")
        return config

    except Exception as e:
        print(f"Error loading sites config from S3: {e}")
        raise


def send_scrape_jobs(sites: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    Send scraping jobs to SQS.

    Returns:
        {"sent": count, "failed": count}
    """
    sent = 0
    failed = 0

    for site in sites:
        try:
            message = {
                "show_name": site['name'],
                "url": site['url'],
                "selectors": site.get('selectors', {})
            }

            sqs.send_message(
                QueueUrl=QUEUE_URL,
                MessageBody=json.dumps(message),
                MessageAttributes={
                    'show_name': {
                        'StringValue': site['name'],
                        'DataType': 'String'
                    }
                }
            )

            sent += 1
            print(f"Queued scrape job for {site['name']}")

        except Exception as e:
            print(f"Failed to queue job for {site['name']}: {e}")
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
    """
    Lambda handler triggered by EventBridge scheduler.

    Event structure (from EventBridge):
    {
        "version": "0",
        "id": "...",
        "detail-type": "Scheduled Event",
        "source": "aws.scheduler",
        "time": "2026-03-01T06:00:00Z",
        ...
    }
    """
    print(f"Starting daily scrape job at {datetime.now(timezone.utc).isoformat()}")

    try:
        # Load sites configuration
        config = load_sites_config()
        sites = config.get('sites', [])

        if not sites:
            error_msg = "No sites found in configuration"
            print(error_msg)
            send_alert("Scrape Job Failed", error_msg)
            return {
                "statusCode": 400,
                "body": json.dumps({"error": error_msg})
            }

        # Send jobs to SQS
        result = send_scrape_jobs(sites)

        print(f"Queued {result['sent']} scrape jobs, {result['failed']} failed")

        # Send summary alert if any failures
        if result['failed'] > 0:
            send_alert(
                "Scrape Job Queueing Issues",
                f"Successfully queued: {result['sent']}\n"
                f"Failed to queue: {result['failed']}\n"
                f"Total sites: {len(sites)}\n"
                f"Time: {datetime.now(timezone.utc).isoformat()}"
            )

        return {
            "statusCode": 200,
            "body": json.dumps({
                "queued": result['sent'],
                "failed": result['failed'],
                "total_sites": len(sites),
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
