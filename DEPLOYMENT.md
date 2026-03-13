# West End Scraper - AWS Deployment Guide

Complete guide for deploying the West End theatre cast scraper to AWS.

## Prerequisites

### 1. Install Required Tools

```bash
# AWS CLI
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install

# AWS SAM CLI
pip install aws-sam-cli

# Docker (required for building Lambda container)
# See: https://docs.docker.com/get-docker/
```

### 2. Configure AWS Credentials

```bash
aws configure

# You'll need:
# - AWS Access Key ID
# - AWS Secret Access Key
# - Default region (e.g., us-east-1)
# - Output format (json)
```

### 3. Prepare Anthropic API Key

You'll need an Anthropic API key. The deployment script will store it in AWS Secrets Manager.

Get your API key from: https://console.anthropic.com/settings/keys

---

## Quick Start

### 1. Deploy to Development

```bash
./deploy.sh dev --guided
```

This will:
- Prompt for your Anthropic API key (stored in Secrets Manager)
- Build the Lambda container images
- Deploy all infrastructure to AWS
- Create DynamoDB tables, SQS queues, Lambda functions, etc.

### 2. Upload Sites Configuration

```bash
# Get the S3 bucket name from stack outputs
BUCKET=$(aws cloudformation describe-stacks \
  --stack-name west-end-scraper-dev \
  --query 'Stacks[0].Outputs[?OutputKey==`SitesConfigBucket`].OutputValue' \
  --output text)

# Upload your sites config
aws s3 cp sites/west_end.json s3://${BUCKET}/west_end.json
```

### 3. Test Manually

```bash
# Get the SQS queue URL
QUEUE_URL=$(aws cloudformation describe-stacks \
  --stack-name west-end-scraper-dev \
  --query 'Stacks[0].Outputs[?OutputKey==`ScrapeJobsQueueUrl`].OutputValue' \
  --output text)

# Send a test scrape job
aws sqs send-message \
  --queue-url $QUEUE_URL \
  --message-body '{
    "show_name": "Hamilton",
    "url": "https://hamiltonmusical.com/london/cast",
    "selectors": {}
  }'

# Watch the logs
aws logs tail /aws/lambda/west-end-scraper-dev --follow
```

---

## Deployment Environments

### Development (`dev`)
- **Stack name:** `west-end-scraper-dev`
- **Schedule:** Disabled (manual triggers only)
- **Alarms:** Disabled
- **Cost:** ~$1-2/month (minimal usage)

Use this for:
- Testing new sites
- Validating scraper changes
- Development and debugging

### Production (`prod`)
- **Stack name:** `west-end-scraper-prod`
- **Schedule:** Daily at 6 AM UTC
- **Alarms:** Enabled (email alerts)
- **Cost:** ~$3-5/month (daily scrapes)

Use this for:
- Live production scraping
- Reliable daily data collection

---

## Deployment Commands

### Initial Deployment (Guided)

```bash
# Development
./deploy.sh dev --guided

# Production
./deploy.sh prod --guided
```

The guided mode will:
- Prompt for parameters (email for alerts, etc.)
- Create a `samconfig.toml` with your settings
- Store configuration for future deployments

### Subsequent Deployments

```bash
# Development (uses samconfig.toml)
./deploy.sh dev

# Production
./deploy.sh prod
```

### Skip Build (Faster Redeployment)

If you only changed the SAM template (not Lambda code):

```bash
./deploy.sh dev --skip-build
```

---

## Infrastructure Components

### DynamoDB Tables

1. **WestEndScrapes-{env}** (Source of truth)
   - Stores all scrape results (immutable)
   - DynamoDB Streams enabled
   - Point-in-time recovery (prod only)

2. **WestEndActorIndex-{env}** (Actor → Shows)
   - Fast lookups for actor's show history
   - GSI for current shows only

3. **WestEndShowIndex-{env}** (Show → Actors)
   - Fast lookups for current/historical cast
   - Indexed by show and actor

### Lambda Functions

1. **west-end-scraper-{env}**
   - Container image (2GB memory, 5 min timeout)
   - Triggered by SQS
   - Scrapes websites using Selenium + Claude

2. **west-end-post-processor-{env}**
   - Python runtime (512MB memory, 1 min timeout)
   - Triggered by DynamoDB Streams
   - Updates index tables, validates data quality

3. **west-end-schedule-target-{env}**
   - Python runtime (256MB memory, 30 sec timeout)
   - Triggered by EventBridge (prod only)
   - Sends scrape jobs to SQS

### SQS Queues

- **west-end-scrape-jobs-{env}** (Main queue)
- **west-end-scrape-jobs-dlq-{env}** (Dead-letter queue)

### S3 Bucket

- **west-end-scraper-config-{env}-{account-id}**
  - Stores sites configuration
  - Versioning enabled

### SNS Topic

- **west-end-scraper-alerts-{env}**
  - Receives alerts for failures, data quality issues

### EventBridge Schedule

- **west-end-daily-scrape-{env}** (prod only)
  - Triggers daily at 6 AM UTC

---

## Configuration

### Sites Configuration (S3)

Create a `sites/west_end.json` file:

```json
{
  "sites": [
    {
      "name": "Hamilton",
      "url": "https://hamiltonmusical.com/london/cast",
      "selectors": {
        "cast_section": "div.cast-list",
        "role_elements": "div.role",
        "actor_elements": "div.actor"
      }
    },
    {
      "name": "Wicked",
      "url": "https://wickedthemusical.co.uk/cast",
      "selectors": {}
    }
  ]
}
```

Upload to S3 after deployment:

```bash
aws s3 cp sites/west_end.json s3://${BUCKET_NAME}/west_end.json
```

### Email Alerts (Production)

To receive email alerts, set the `ALERT_EMAIL` environment variable before deployment:

```bash
export ALERT_EMAIL="you@example.com"
./deploy.sh prod --guided
```

You'll receive a confirmation email - click the link to confirm subscription.

---

## Monitoring

### CloudWatch Logs

```bash
# Scraper logs
aws logs tail /aws/lambda/west-end-scraper-prod --follow

# Post-processor logs
aws logs tail /aws/lambda/west-end-post-processor-prod --follow

# Schedule target logs
aws logs tail /aws/lambda/west-end-schedule-target-prod --follow
```

### CloudWatch Metrics

Key metrics to monitor:
- Lambda invocations, errors, duration
- SQS message age, DLQ depth
- DynamoDB consumed capacity, throttles

Access via AWS Console: CloudWatch → Metrics

### Custom Dashboards

Create a CloudWatch dashboard:

```bash
aws cloudwatch put-dashboard \
  --dashboard-name west-end-scraper-prod \
  --dashboard-body file://cloudwatch-dashboard.json
```

---

## Querying Data

### DynamoDB Queries

#### Get Current Cast for a Show

```python
import boto3

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('WestEndShowIndex-prod')

response = table.get_item(
    Key={
        'PK': 'SHOW#hamilton',
        'SK': 'CURRENT'
    }
)

print(response['Item']['cast'])
```

#### Get All Shows for an Actor

```python
table = dynamodb.Table('WestEndActorIndex-prod')

response = table.query(
    KeyConditionExpression='PK = :pk',
    ExpressionAttributeValues={
        ':pk': 'ACTOR#John Doe'
    }
)

for item in response['Items']:
    print(f"{item['show_name']}: {item['roles']}")
```

#### Get Scrape History for a Show

```python
table = dynamodb.Table('WestEndScrapes-prod')

response = table.query(
    KeyConditionExpression='PK = :pk',
    ExpressionAttributeValues={
        ':pk': 'SHOW#hamilton'
    },
    ScanIndexForward=False,  # Newest first
    Limit=10
)

for scrape in response['Items']:
    print(f"{scrape['scraped_at']}: {scrape['cast_count']} cast members")
```

---

## Troubleshooting

### Scraper Failing

**Symptoms:** Messages in DLQ, failed scrape status in DynamoDB

**Debugging:**

1. Check Lambda logs:
   ```bash
   aws logs tail /aws/lambda/west-end-scraper-prod --follow
   ```

2. Check DLQ for failed messages:
   ```bash
   aws sqs receive-message \
     --queue-url <DLQ_URL> \
     --max-number-of-messages 10
   ```

3. Test scraper locally:
   ```bash
   # Run scraper in Docker
   docker build -t scraper -f lambda/scraper/Dockerfile.scraper .
   docker run -e ANTHROPIC_API_KEY=xxx scraper
   ```

### Data Quality Issues

**Symptoms:** Alerts about cast count drops, validation failures

**Resolution:**

1. Check scrape results in DynamoDB:
   ```bash
   aws dynamodb query \
     --table-name WestEndScrapes-prod \
     --key-condition-expression 'PK = :pk' \
     --expression-attribute-values '{":pk":{"S":"SHOW#hamilton"}}' \
     --scan-index-forward false \
     --limit 2
   ```

2. Compare current and previous scrapes
3. Check if website structure changed
4. Update selectors in sites configuration if needed

### No Scrapes Running

**Symptoms:** No activity, no logs

**Debugging:**

1. Check EventBridge schedule is enabled:
   ```bash
   aws scheduler get-schedule --name west-end-daily-scrape-prod
   ```

2. Manually trigger schedule target:
   ```bash
   aws lambda invoke \
     --function-name west-end-schedule-target-prod \
     response.json

   cat response.json
   ```

3. Check SQS queue for messages:
   ```bash
   aws sqs get-queue-attributes \
     --queue-url <QUEUE_URL> \
     --attribute-names All
   ```

---

## Cost Optimization

### Current Costs (~$3-5/month for 50 shows, daily)

- Lambda (scraper): ~$2/month
- Lambda (post-processor): ~$0.10/month
- DynamoDB: ~$1.50/month
- SQS: ~$0.01/month
- S3: <$0.01/month

### Tips to Reduce Costs

1. **Reduce scrape frequency** (weekly instead of daily)
2. **Use DynamoDB On-Demand** (already configured)
3. **Delete old scrape data** (add TTL to Scrapes table)
4. **Reduce Lambda memory** if scraping is fast enough

### Adding TTL (Time-to-Live) to Scrapes Table

Keep only last 90 days of scrape data:

```bash
aws dynamodb update-time-to-live \
  --table-name WestEndScrapes-prod \
  --time-to-live-specification "Enabled=true, AttributeName=ttl"
```

Then update Lambda to add TTL field:
```python
item['ttl'] = int(time.time()) + (90 * 24 * 60 * 60)  # 90 days
```

---

## Updating the Stack

### Update Lambda Code

1. Make changes to Lambda functions
2. Redeploy:
   ```bash
   ./deploy.sh prod
   ```

### Update Infrastructure

1. Edit `template.yaml`
2. Redeploy:
   ```bash
   ./deploy.sh prod
   ```

SAM/CloudFormation will automatically detect changes and update only what's needed.

### Update Sites Configuration

```bash
# Edit sites/west_end.json locally
# Then upload to S3
aws s3 cp sites/west_end.json s3://${BUCKET_NAME}/west_end.json

# Changes take effect on next scheduled run
# Or trigger manually
aws lambda invoke \
  --function-name west-end-schedule-target-prod \
  response.json
```

---

## Cleanup / Deletion

### Delete Stack

```bash
# Delete development stack
aws cloudformation delete-stack --stack-name west-end-scraper-dev

# Delete production stack
aws cloudformation delete-stack --stack-name west-end-scraper-prod
```

**Note:** This will delete ALL data including DynamoDB tables. Backup first if needed!

### Delete Secrets

```bash
aws secretsmanager delete-secret \
  --secret-id west-end-scraper/anthropic-api-key \
  --force-delete-without-recovery
```

### Empty S3 Bucket First

CloudFormation cannot delete non-empty buckets:

```bash
BUCKET=$(aws cloudformation describe-stacks \
  --stack-name west-end-scraper-prod \
  --query 'Stacks[0].Outputs[?OutputKey==`SitesConfigBucket`].OutputValue' \
  --output text)

aws s3 rm s3://${BUCKET} --recursive
```

---

## Security Best Practices

1. **API Keys:** Never commit API keys to Git. Always use Secrets Manager.
2. **IAM Roles:** Lambda functions use least-privilege IAM roles (defined in template.yaml)
3. **Encryption:** All data encrypted at rest (DynamoDB, S3, Secrets Manager)
4. **VPC:** Not required (no database connections, all AWS services)
5. **Public Access:** No public endpoints (all internal AWS services)

---

## Support

For issues or questions:

1. Check CloudWatch Logs
2. Review DynamoDB data
3. Test scraper locally
4. Check architecture documentation: `docs/aws-architecture.md`

---

## Next Steps

1. ✅ Deploy to dev environment
2. ✅ Upload sites configuration
3. ✅ Test with a few shows manually
4. ✅ Verify data in DynamoDB
5. ✅ Deploy to prod with scheduling enabled
6. ✅ Subscribe to email alerts
7. ✅ Monitor for a week
8. 🚀 Scale to 50+ shows!
