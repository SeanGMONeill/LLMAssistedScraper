# Direct LLM vs Selector-Based Extraction

This project now includes **two parallel implementations** for A/B testing in production:

## 🔍 Overview

| Feature | Original (Selector-based) | Direct (LLM-only) |
|---------|--------------------------|-------------------|
| **Script** | `scraper_cli.py` | `scraper_cli_direct.py` |
| **LLM Used** | OpenAI GPT-4o-mini | Claude Haiku 4.5 |
| **Approach** | LLM → Values → Infer CSS Selectors → Cache | LLM → Direct JSON Extraction |
| **Caching** | ✅ Yes (saves selectors) | ❌ No (LLM every run) |
| **Code Size** | ~1,100 lines | ~600 lines |
| **API Key** | `openai_key.txt` | `anthropic_key.txt` |
| **Output Dir** | `results/` | `results_direct/` |

---

## 📊 Cost Analysis (50 sites, weekly scraping)

### Original Approach
- **Initial setup**: 50 LLM calls × $0.01 = **$0.50**
- **Subsequent runs**: $0 (uses cached selectors)
- **Annual cost**: **~$0.50**

### Direct Approach
- **Per scrape**: 50 sites × $0.005/site = **$0.25**
- **Weekly**: $0.25 × 52 = **$13/year**
- **Annual cost**: **~$13**

**Difference: $12.50/year ($1/month)**

---

## ⚖️ Trade-offs

### Original (Selector-based) Wins On:

✅ **Cost at scale** - Free after initial setup
✅ **Speed** - Instant DOM queries (no LLM latency)
✅ **Deterministic** - Same selectors = same results

### Direct (LLM-only) Wins On:

✅ **Simplicity** - 50% less code to maintain
✅ **Resilience** - Adapts to HTML structure changes automatically
✅ **Development speed** - No debugging complex selector logic
✅ **Maintenance** - No cache invalidation needed

---

## 🚀 Usage

### Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Create API key files
echo "your-openai-key" > openai_key.txt
echo "your-anthropic-key" > anthropic_key.txt
```

### Run Original (Selector-based)

```bash
# First run - infers selectors
python scraper_cli.py run sites/books.json

# Subsequent runs - uses cached selectors
python scraper_cli.py run sites/books.json

# Force re-inference (if site changed)
python scraper_cli.py run sites/books.json --no-cache
```

### Run Direct (LLM-only)

```bash
# Always calls Claude - no caching
python scraper_cli_direct.py run sites/books.json

# Works with same site configs
python scraper_cli_direct.py run sites/cast_lists.json
```

---

## 🧪 A/B Testing in Production

### Compare Both Approaches

```bash
# Run both on the same site
python scraper_cli.py run sites/books.json --site waterstones_example
python scraper_cli_direct.py run sites/books.json --site waterstones_example

# Compare results
python scraper_cli_direct.py compare \
  results/books_waterstones_example.json \
  results_direct/books_waterstones_example.json
```

### What to Measure

1. **Accuracy** - Do both extract the same data?
2. **Completeness** - Which finds more records/fields?
3. **Speed** - Time each run (first run vs cached)
4. **Reliability** - Run weekly for 4 weeks, track failures

---

## 📈 Recommended Evaluation Plan

### Week 1: Initial Test
- Run both approaches on 10 representative sites
- Manually verify accuracy
- Compare output completeness

### Week 2-4: Stability Test
- Run both weekly on same 10 sites
- Track failure rates
- Note any HTML structure changes

### Week 5: Decision
- If **sites are stable** → Use original (saves $13/year)
- If **sites change frequently** → Use direct (worth $1/month for resilience)
- If **accuracy differs** → Use whichever is more accurate

---

## 🔧 Schema Compatibility

Both approaches use the same site configurations (`sites/*.json`) but optimized schemas are provided:

| Schema Type | Original | Direct (Optimized) |
|-------------|----------|-------------------|
| Books | `schemas/books.json` | `schemas/books_direct.json` |
| Theatre Cast | `schemas/cast_lists.json` | `schemas/theatre_cast_direct.json` |

The direct schemas have:
- Clearer instructions for Claude
- Single-string content format (easier to read)
- More explicit extraction rules

---

## 💡 Hybrid Option (Future)

If you find the direct approach more reliable but want to save costs, consider:

1. **LLM-first with caching** - Cache the LLM *response* instead of selectors
2. **Auto-rebuild on failure** - Use selectors, but auto-switch to LLM if extraction fails
3. **Periodic refresh** - Use selectors but re-infer monthly (detect HTML changes)

---

## 📁 File Structure

```
LLMAssistedScraper/
├── scraper_cli.py              # Original selector-based CLI
├── scraper_cli_direct.py       # New direct LLM CLI
├── webdriver_extractor.py      # Complex selector inference (274 lines)
├── direct_extractor.py         # Simple page loader (60 lines)
├── llm_client.py               # OpenAI client
├── anthropic_client.py         # Claude client
├── results/                    # Original scraper output
├── results_direct/             # Direct scraper output
├── rules/                      # Cached CSS selectors (original only)
└── schemas/
    ├── books.json              # Original schema
    ├── books_direct.json       # Optimized for Claude
    ├── cast_lists.json         # Original theatre schema
    └── theatre_cast_direct.json # Optimized for Claude
```

---

## 🎯 Recommendation

For **50 West End shows scraped weekly**:

- Start with **direct approach** for first month
- If sites prove very stable (no HTML changes), switch to original
- If sites change even once, direct approach pays for itself in saved debugging time

The $12.50/year difference is negligible for the development time saved.
