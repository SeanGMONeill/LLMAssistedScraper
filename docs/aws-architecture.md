# AWS Architecture for West End Cast Tracker

## Overview

Production-ready serverless architecture for scraping and tracking West End theatre cast information.

## Architecture Diagram

```
┌─────────────────┐
│  EventBridge    │  Trigger: Daily at 6 AM UTC
│  (Scheduler)    │  Rule: cron(0 6 * * ? *)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   SQS Queue     │  Standard queue
│  (scrape-jobs)  │  Visibility timeout: 5 min
│                 │  DLQ after 3 retries
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────┐
│   Lambda: Scraper               │  Runtime: Python 3.12 (Container)
│   ├─ direct_extractor.py        │  Memory: 2048 MB
│   ├─ anthropic_client.py        │  Timeout: 5 minutes
│   └─ Chrome/ChromeDriver         │  Concurrency: 10
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│   DynamoDB: Scrapes             │  Immutable audit trail
│   (Source of Truth)             │  Stream enabled
│                                 │
│   PK: SHOW#{show_name}          │
│   SK: SCRAPE#{iso_timestamp}    │
└────────┬────────────────────────┘
         │ (DynamoDB Stream)
         ▼
┌─────────────────────────────────┐
│   Lambda: Post-Processor        │  Runtime: Python 3.12
│   ├─ Compare scrapes            │  Memory: 512 MB
│   ├─ Validate data quality      │  Timeout: 1 minute
│   └─ Update indexes             │
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│   DynamoDB: ActorIndex          │  For actor → shows queries
│   DynamoDB: ShowIndex           │  For show → actors queries
│                                 │
│   + SNS for alerts              │  Data quality warnings
└─────────────────────────────────┘
```

## DynamoDB Table Schemas

### 1. Scrapes Table (Source of Truth)

**Purpose:** Immutable record of every scrape. Never updated, only inserted.

```yaml
TableName: WestEndScrapes
BillingMode: PAY_PER_REQUEST
StreamEnabled: true
StreamViewType: NEW_AND_OLD_IMAGES

PrimaryKey:
  PartitionKey: PK (String)    # SHOW#{show_name}
  SortKey: SK (String)         # SCRAPE#{iso_timestamp}

Attributes:
  - show_name: String           # "Hamilton"
  - cast: List<Map>             # [{role: "Hamilton", actor: "John Doe"}, ...]
  - source_url: String          # URL scraped
  - scraped_at: String          # ISO timestamp
  - cast_count: Number          # len(cast) - for validation
  - scrape_status: String       # "success" | "failed" | "validation_failed"
  - error_msg: String           # If failed
  - scraper_version: String     # For debugging

GSI-1 (Query by date):
  PartitionKey: date_key (String)     # DATE#{YYYY-MM-DD}
  SortKey: PK (String)                # SHOW#{show_name}
  ProjectionType: ALL

TTL: None (keep forever for historical analysis)
```

**Example Items:**
```json
{
  "PK": "SHOW#hamilton",
  "SK": "SCRAPE#2026-03-01T06:15:23Z",
  "show_name": "Hamilton",
  "cast": [
    {"role": "Alexander Hamilton", "actor": "John Doe"},
    {"role": "Aaron Burr", "actor": "Jane Smith"}
  ],
  "source_url": "https://hamiltonmusical.com/london/cast",
  "scraped_at": "2026-03-01T06:15:23Z",
  "cast_count": 20,
  "scrape_status": "success",
  "scraper_version": "1.0.0",
  "date_key": "DATE#2026-03-01"
}
```

### 2. ActorIndex Table

**Purpose:** Fast lookups for "which shows has this actor been in?"

```yaml
TableName: WestEndActorIndex
BillingMode: PAY_PER_REQUEST

PrimaryKey:
  PartitionKey: PK (String)    # ACTOR#{actor_name}
  SortKey: SK (String)         # SHOW#{show_name}#JOINED#{timestamp}

Attributes:
  - actor_name: String          # "John Doe"
  - show_name: String           # "Hamilton"
  - roles: List<String>         # ["Alexander Hamilton", "Alternate Hamilton"]
  - first_seen: String          # ISO timestamp
  - last_seen: String           # ISO timestamp
  - is_current: Boolean         # Currently in show?
  - appearance_count: Number    # How many scrapes captured them

GSI-1 (Current shows only):
  PartitionKey: is_current (Number)   # 1 for current, 0 for past
  SortKey: PK (String)                # ACTOR#{actor_name}
  ProjectionType: ALL
```

**Example Items:**
```json
{
  "PK": "ACTOR#John Doe",
  "SK": "SHOW#hamilton#JOINED#2026-01-15T06:00:00Z",
  "actor_name": "John Doe",
  "show_name": "Hamilton",
  "roles": ["Alexander Hamilton"],
  "first_seen": "2026-01-15T06:00:00Z",
  "last_seen": "2026-03-01T06:15:23Z",
  "is_current": true,
  "appearance_count": 15
}
```

### 3. ShowIndex Table

**Purpose:** Fast lookups for "current cast" and "cast history for a show"

```yaml
TableName: WestEndShowIndex
BillingMode: PAY_PER_REQUEST

PrimaryKey:
  PartitionKey: PK (String)    # SHOW#{show_name}
  SortKey: SK (String)         # CURRENT or ACTOR#{actor_name}#{timestamp}

Attributes:
  # For CURRENT cast:
  - cast: List<Map>             # Current cast list
  - last_updated: String        # ISO timestamp
  - cast_count: Number

  # For ACTOR history:
  - actor_name: String
  - roles: List<String>
  - first_seen: String
  - last_seen: String
  - is_current: Boolean
```

**Example Items:**
```json
{
  "PK": "SHOW#hamilton",
  "SK": "CURRENT",
  "cast": [
    {"role": "Alexander Hamilton", "actor": "John Doe"},
    {"role": "Aaron Burr", "actor": "Jane Smith"}
  ],
  "last_updated": "2026-03-01T06:15:23Z",
  "cast_count": 20
}

{
  "PK": "SHOW#hamilton",
  "SK": "ACTOR#John Doe#2026-01-15T06:00:00Z",
  "actor_name": "John Doe",
  "roles": ["Alexander Hamilton"],
  "first_seen": "2026-01-15T06:00:00Z",
  "last_seen": "2026-03-01T06:15:23Z",
  "is_current": true
}
```

## Access Patterns & Queries

### Query 1: Get current cast for a show
```python
response = show_index_table.get_item(
    Key={
        'PK': 'SHOW#hamilton',
        'SK': 'CURRENT'
    }
)
```

### Query 2: Get all shows for an actor
```python
response = actor_index_table.query(
    KeyConditionExpression='PK = :pk',
    ExpressionAttributeValues={
        ':pk': 'ACTOR#John Doe'
    }
)
```

### Query 3: Get cast history for a show
```python
response = show_index_table.query(
    KeyConditionExpression='PK = :pk AND begins_with(SK, :sk)',
    ExpressionAttributeValues={
        ':pk': 'SHOW#hamilton',
        ':sk': 'ACTOR#'
    }
)
```

### Query 4: Get role history (e.g., who played Elphaba)
```python
# Query all scrapes for Wicked
response = scrapes_table.query(
    KeyConditionExpression='PK = :pk',
    ExpressionAttributeValues={
        ':pk': 'SHOW#wicked'
    }
)

# Filter in application code for role "Elphaba"
elphaba_history = []
for item in response['Items']:
    for cast_member in item['cast']:
        if cast_member['role'] == 'Elphaba':
            elphaba_history.append({
                'actor': cast_member['actor'],
                'scraped_at': item['scraped_at']
            })
```

### Query 5: All scrapes from today (health check)
```python
response = scrapes_table.query(
    IndexName='GSI-1',
    KeyConditionExpression='date_key = :date',
    ExpressionAttributeValues={
        ':date': 'DATE#2026-03-01'
    }
)
```

## Data Validation Rules

### Scraper Lambda
- ✅ Cast count > 0
- ✅ Each cast member has role AND actor
- ✅ No duplicate role+actor combinations

### Post-Processor Lambda
- ⚠️ Cast count dropped >50% vs previous scrape → Alert, don't update indexes
- ⚠️ Cast count = 0 → Alert, don't update indexes
- ⚠️ All actors changed (0% overlap) → Alert, needs manual review
- ✅ 10-30% actor changes → Normal, update indexes
- ℹ️ No changes → Skip index updates (optimization)

### Alerts sent to SNS when:
1. Scraper fails (exception, timeout)
2. Validation fails (suspicious data)
3. Site structure changed (scraper returns 0 results)

## Cost Estimates (50 shows, daily scrapes)

| Service | Usage | Monthly Cost |
|---------|-------|--------------|
| Lambda (Scraper) | 50 scrapes/day × 3 min × 2 GB | ~$2 |
| Lambda (Post-Processor) | 50 invocations/day × 10s × 512 MB | ~$0.10 |
| DynamoDB (3 tables) | ~1,500 writes/day, 10,000 reads/day | ~$1.50 |
| SQS | 1,500 requests/day | ~$0.01 |
| EventBridge | 1 event/day | Free |
| **Total** | | **~$3.60/month** |

Storage (1 year): ~50 KB/scrape × 50 shows × 365 days = 900 MB → $0.25/month

## Deployment Environments

### Development
- Stack name: `west-end-scraper-dev`
- Schedule: Manual trigger only (no EventBridge)
- Table names: `WestEndScrapes-dev`, etc.

### Production
- Stack name: `west-end-scraper-prod`
- Schedule: Daily at 6 AM UTC
- Table names: `WestEndScrapes-prod`, etc.
- Alarms enabled (SNS → Email)

## Security

- Lambda execution roles: Least privilege (only access to own tables/queues)
- No public endpoints (all internal AWS services)
- DynamoDB: Encryption at rest (AWS managed keys)
- SQS: Encryption in transit
- Secrets: Anthropic API key stored in Secrets Manager
- VPC: Not needed (all AWS services, no database connections)

## Monitoring & Observability

### CloudWatch Metrics
- Lambda errors, duration, throttles
- SQS message age, DLQ depth
- DynamoDB throttles, consumed capacity

### CloudWatch Logs
- All Lambda logs retained for 30 days
- Log groups: `/aws/lambda/scraper`, `/aws/lambda/post-processor`

### Custom Metrics (via Post-Processor)
- Successful scrapes per day
- Average cast count per show
- Data quality score (% of scrapes passing validation)

### Alarms
1. **Scraper Error Rate > 10%** → SNS email
2. **DLQ has messages** → SNS email
3. **No successful scrapes in 24 hours** → SNS email

## Disaster Recovery

- **Data loss:** Impossible (DynamoDB + backups)
- **Failed deployment:** CloudFormation rollback
- **Bad data:** Reprocess from Scrapes table (immutable source of truth)
- **Lambda bug:** Deploy new version, trigger reprocessing from DynamoDB Stream

## Reprocessing Strategy

If you need to rebuild ActorIndex/ShowIndex:

```bash
# 1. Delete index tables
aws dynamodb delete-table --table-name WestEndActorIndex-prod
aws dynamodb delete-table --table-name WestEndShowIndex-prod

# 2. Recreate via CloudFormation
sam deploy

# 3. Trigger reprocessing (reads all scrapes, rebuilds indexes)
aws lambda invoke --function-name reprocess-all-scrapes \
  --payload '{"start_date": "2026-01-01"}' \
  response.json
```

## Future Enhancements

1. **API Gateway + Lambda** → Public API for querying data
2. **S3 + Athena** → Long-term archival and analytics
3. **Step Functions** → More complex orchestration (parallel scrapes with retry logic)
4. **CloudFront + S3** → Static website for browsing cast data
5. **OpenSearch** → Full-text search across actors/shows/roles
