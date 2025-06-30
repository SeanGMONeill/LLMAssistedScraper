# 🕷️ LLM-Assisted Web Scraper

An intelligent web scraper that uses AI to automatically find and extract structured data from websites. The scraper can handle complex scenarios where data fields are scattered across different DOM elements, using Large Language Models to understand page structure and create precise extraction rules.

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
│ • openai_key.txt│   │ • Invalidation   │    │   Formats       │
└─────────────────┘    └──────────────────┘    └─────────────────┘
```

## 🤝 Legacy Support

The new CLI maintains full backward compatibility:
- All existing JSON configurations work unchanged
- Original Python scripts (`find_selectors.py`) still functional
- Same output formats and file structures
- Existing cache files are compatible

## 📦 Dependencies

Core dependencies:
- `selenium` - Web automation
- `openai` - LLM integration
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