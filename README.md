# 🕷️ LLM-Assisted Web Scraper

An intelligent web scraper that uses AI to automatically find and extract structured data from websites. The scraper can handle complex scenarios where data fields are scattered across different DOM elements, using Large Language Models to understand page structure and create precise extraction rules.

## 🚀 Now Production-Ready on AWS!

**NEW:** Full serverless AWS deployment for automated scraping of 50+ West End theatre cast pages.

**Quick Deploy:**
```bash
./deploy.sh prod --guided
```

**Features:**
- ⏰ **Scheduled scraping** - Daily automatic updates
- 📊 **DynamoDB storage** - Queryable cast history and actor indexes
- 🔍 **IMDb-style queries** - "Show me all shows for this actor"
- 🛡️ **Data validation** - Automatic quality checks and alerts
- 💰 **Cost-effective** - ~$3-5/month for 50 sites daily
- 🔔 **Email alerts** - Notifications for failures and cast changes

See **[DEPLOYMENT.md](DEPLOYMENT.md)** for complete AWS deployment guide.

See **[docs/aws-architecture.md](docs/aws-architecture.md)** for architecture details.

---

## 🆕 Two Approaches Available

This project now includes **two parallel implementations** for A/B testing:

| Approach | CLI | Cost/Year (50 sites, weekly) | Best For |
|----------|-----|------------------------------|----------|
| **Selector-based** | `scraper_cli.py` | ~$0.50 | Stable sites, cost-sensitive |
| **Direct LLM** | `scraper_cli_direct.py` | ~$13 | Changing sites, simplicity |

**See [COMPARISON.md](COMPARISON.md) for detailed analysis and evaluation guide.**

## ✨ Features

- **🧠 AI-Powered**: Uses LLM to analyze page structure and infer extraction rules
- **🔄 Self-Healing**: Falls back to AI re-analysis when cached selectors fail
- **🎯 Precise Extraction**: Filters results using LLM-provided expected values
- **⚡ Smart Caching**: Saves extraction rules for fast subsequent runs
- **🎨 Rich CLI**: Beautiful command-line interface with progress indicators
- **📊 Multiple Output Formats**: JSON, table, and more
- **🛡️ Robust**: Handles separate DOM elements, dynamic content, and edge cases

## 🚀 Quick Start

### 1. Setup
Install Python dependencies:
```bash
python -m pip install -r requirements.txt
```

Install ChromeDriver (Mac):
```bash
brew install --cask chromedriver
```

### 2. Add OpenAI API Key
Create a file named `openai_key.txt` with your OpenAI API key:
```bash
echo "your-openai-api-key-here" > openai_key.txt
```

### 3. Run the Scraper
```bash
# Run with beautiful table output
python scraper_cli.py run sites/books.json --format table

# Run specific site only
python scraper_cli.py run sites/books.json --site waterstones_the_truth

# Force fresh analysis (ignore cached rules)
python scraper_cli.py run sites/books.json --no-cache
```

## 📖 CLI Commands

### 🏃 `run` - Extract data from websites
```bash
python scraper_cli.py run CONFIG_FILE [OPTIONS]
```

**Options:**
- `--site SITE_ID` - Run only specific site by ID
- `--no-cache` - Force re-inference of rules (ignore cached selectors)
- `--output-dir DIR` - Output directory for results (default: results)
- `--format FORMAT` - Output format: json, table (default: json)

**Examples:**
```bash
# Basic run with JSON output
python scraper_cli.py run sites/books.json

# Run with beautiful table display
python scraper_cli.py run sites/books.json --format table

# Run specific site and force fresh analysis
python scraper_cli.py run sites/books.json --site waterstones_the_truth --no-cache

# Custom output directory
python scraper_cli.py run sites/books.json --output-dir my_results
```

### 📋 `list-sites` - Show sites in configuration
```bash
python scraper_cli.py list-sites CONFIG_FILE
```

Displays all sites with their URLs and cache status:
```
Sites in sites/books.json
Schema: ['author', 'title', 'isbn', 'cost']

╭───────────────────────┬────────┬──────────────────────────────┬──────────────╮
│ ID                    │ Name   │ URL                          │ Cached Rules │
├───────────────────────┼────────┼──────────────────────────────┼──────────────┤
│ waterstones_the_truth │ Demo 1 │ https://www.waterstones.com… │      ✅      │
╰───────────────────────┴────────┴──────────────────────────────┴──────────────╯
```

### 🗑️ `clear-cache` - Clear cached extraction rules
```bash
# Clear cache for specific site
python scraper_cli.py clear-cache --site waterstones_the_truth

# Clear all cache files
python scraper_cli.py clear-cache

# Skip confirmation prompt
python scraper_cli.py clear-cache --confirm
```

### 📊 `cache-status` - Show cache statistics
```bash
python scraper_cli.py cache-status
```

Shows all cached rule files with sizes and modification dates:
```
📁 Found 2 cached rule file(s):

╭─────────────────────────────────┬─────────────┬──────────────────╮
│ File                            │        Size │ Modified         │
├─────────────────────────────────┼─────────────┼──────────────────┤
│ book_waterstones_the_truth.json │ 1,355 bytes │ 2025-06-30 21:01 │
│ cast_list_stranger_things.json  │ 3,042 bytes │ 2025-06-11 13:39 │
╰─────────────────────────────────┴─────────────┴──────────────────╯
```

## ⚙️ Configuration

The scraper uses JSON configuration files to define sites and schemas:

### Sites Configuration (`sites/books.json`)
```json
{
    "schema": "schemas/books.json",
    "id": "book",
    "sites": [
        {
            "name": "Waterstones Book Page",
            "url": "https://www.waterstones.com/book/the-truth/terry-pratchett/9780552167635",
            "id": "waterstones_the_truth"
        }
    ]
}
```

### Schema Configuration (`schemas/books.json`)
```json
{
    "prompt": [
        {
            "role": "system",
            "content": "You are a web-scraping assistant..."
        }
    ],
    "attributes": ["author", "title", "isbn", "cost"]
}
```

## 🔧 Advanced Features

### Self-Healing Architecture
The scraper automatically handles websites where data fields are in separate DOM elements:

1. **First attempt**: Tries to find selectors that capture all fields together
2. **Fallback**: If that fails, finds individual selectors for each field
3. **Smart combination**: Combines individual field results into complete records
4. **Precision filtering**: Uses LLM-provided expected values to filter out noise

### Cache Management
- **Automatic caching**: Saves extraction rules after first successful run
- **Performance**: Cached runs are ~10x faster than fresh analysis
- **Invalidation**: Use `--no-cache` or `clear-cache` when sites change structure
- **Granular control**: Clear cache for specific sites or all sites

### Rich Output
- **Progress indicators**: See real-time status during LLM analysis
- **Colored output**: Green for success, red for errors, yellow for warnings
- **Table format**: Human-readable tables for result inspection
- **Summary reports**: Overview of all processed sites and results

## 🏗️ Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   CLI Layer     │    │   Core Engine    │    │   AI Layer      │
│                 │    │                  │    │                 │
│ • Rich Output   │───▶│ • WebDriver      │───▶│ • LLM Analysis  │
│ • Progress Bars │    │ • Rule Engine    │    │ • Expected      │
│ • Commands      │    │ • Cache Manager  │    │   Values        │
│ • Validation    │    │ • Extractor      │    │ • Prompt Eng.   │
└─────────────────┘    └──────────────────┘    └─────────────────┘
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Config Files  │    │   Cache Layer    │    │   Results       │
│                 │    │                  │    │                 │
│ • sites/*.json  │    │ • rules/*.json   │    │ • results/*.json│
│ • schemas/*.json│    │ • Smart Caching  │    │ • Multiple      │
│ • openai_key.txt│    │ • Invalidation   │    │   Formats       │
└─────────────────┘    └──────────────────┘    └─────────────────┘
```

## 🆕 Direct LLM Approach (Alternative)

A simplified alternative implementation using Claude Haiku for direct extraction:

### Quick Start
```bash
# Create Anthropic API key file
echo "your-anthropic-api-key" > anthropic_key.txt

# Run direct extraction (no caching)
python scraper_cli_direct.py run sites/books.json --format table

# Compare both approaches
./compare_approaches.sh sites/books.json
```

### Key Differences
- **No selector inference** - Claude directly extracts structured data
- **No caching** - LLM called every run (~$0.005/page with Haiku)
- **Simpler codebase** - 50% fewer lines than original
- **More resilient** - Adapts to HTML changes automatically

### When to Use
- Sites that frequently change structure
- One-off or exploratory scraping
- Prefer simplicity over cost optimization
- Budget allows ~$13/year for 50 sites weekly

See [COMPARISON.md](COMPARISON.md) for detailed cost/performance analysis.

## 🤝 Legacy Support

The new CLI maintains full backward compatibility:
- All existing JSON configurations work unchanged
- Original Python scripts (`find_selectors.py`) still functional
- Same output formats and file structures
- Existing cache files are compatible

## 📦 Dependencies

Core dependencies:
- `selenium` - Web automation
- `openai` - LLM integration (original approach)
- `anthropic` - Claude API (direct approach)
- `click` - CLI framework
- `rich` - Beautiful terminal output
- `html2text` - HTML to markdown conversion

## 🛠️ Development

### Running Tests
```bash
python -m unittest test_webdriver_extractor.py -v
```

### Manual Mode (Original Scripts)
```bash
# Traditional approach (still works)
python find_selectors.py
```

## ☁️ AWS Production Deployment

### Architecture

Production-ready serverless architecture for automated scraping:

```
EventBridge (cron) → SQS → Lambda (Scraper) → DynamoDB (Scrapes)
                                                      ↓ (Stream)
                                               Lambda (Post-Processor)
                                                      ↓
                                          DynamoDB (Actor + Show Indexes)
```

### Deployment

```bash
# Prerequisites
# - AWS CLI configured
# - AWS SAM CLI installed
# - Docker running
# - Anthropic API key

# Deploy to development
./deploy.sh dev --guided

# Deploy to production (with daily scheduling)
./deploy.sh prod
```

### Features

**Data Storage:**
- **Scrapes Table** - Immutable audit trail of all scrapes
- **ActorIndex Table** - Query: "Which shows has this actor been in?"
- **ShowIndex Table** - Query: "What's the current cast of Hamilton?"

**Automation:**
- Daily scraping at 6 AM UTC (production only)
- Automatic retry with dead-letter queue
- Email alerts for failures and data quality issues

**Cost:** ~$3-5/month for 50 sites scraped daily

**Monitoring:**
- CloudWatch logs and metrics
- Custom alarms for scraper errors
- SNS alerts for cast changes

### Quick Queries

```python
import boto3

# Get current cast for a show
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('WestEndShowIndex-prod')

response = table.get_item(
    Key={'PK': 'SHOW#hamilton', 'SK': 'CURRENT'}
)
print(response['Item']['cast'])

# Get all shows for an actor
table = dynamodb.Table('WestEndActorIndex-prod')
response = table.query(
    KeyConditionExpression='PK = :pk',
    ExpressionAttributeValues={':pk': 'ACTOR#John Doe'}
)
for item in response['Items']:
    print(f"{item['show_name']}: {item['roles']}")
```

### Documentation

- **[DEPLOYMENT.md](DEPLOYMENT.md)** - Complete deployment guide
- **[docs/aws-architecture.md](docs/aws-architecture.md)** - Architecture details
- **[sites/README.md](sites/README.md)** - Site configuration guide

### Management

```bash
# Upload sites configuration
aws s3 cp sites/west_end.json s3://YOUR-BUCKET/west_end.json

# Trigger manual scrape
aws sqs send-message --queue-url QUEUE_URL \
  --message-body '{"show_name":"Hamilton","url":"...","selectors":{}}'

# View logs
aws logs tail /aws/lambda/west-end-scraper-prod --follow

# Query recent scrapes
aws dynamodb query --table-name WestEndScrapes-prod \
  --key-condition-expression 'PK = :pk' \
  --expression-attribute-values '{":pk":{"S":"SHOW#hamilton"}}' \
  --limit 5
```

---
