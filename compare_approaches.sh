#!/bin/bash
#
# A/B Testing Script - Compare Original vs Direct Extraction
#
# Usage: ./compare_approaches.sh sites/books.json waterstones_example
#

set -e

CONFIG_FILE=${1:-"sites/books.json"}
SITE_ID=${2:-""}

echo "🔬 A/B Testing: Original vs Direct Extraction"
echo "=============================================="
echo ""

# Check for API keys
if [ ! -f "openai_key.txt" ]; then
    echo "❌ Error: openai_key.txt not found"
    echo "   Create this file with your OpenAI API key"
    exit 1
fi

if [ ! -f "anthropic_key.txt" ]; then
    echo "❌ Error: anthropic_key.txt not found"
    echo "   Create this file with your Anthropic API key"
    exit 1
fi

# Build site argument
SITE_ARG=""
if [ -n "$SITE_ID" ]; then
    SITE_ARG="--site $SITE_ID"
fi

echo "📋 Configuration: $CONFIG_FILE"
if [ -n "$SITE_ID" ]; then
    echo "🎯 Target Site: $SITE_ID"
else
    echo "🎯 Target: All sites in config"
fi
echo ""

# Run original approach
echo "🔵 Running ORIGINAL (Selector-based) approach..."
echo "------------------------------------------------"
time python scraper_cli.py run "$CONFIG_FILE" $SITE_ARG --format table

echo ""
echo "🟢 Running DIRECT (LLM-only) approach..."
echo "------------------------------------------------"
time python scraper_cli_direct.py run "$CONFIG_FILE" $SITE_ARG --format table

echo ""
echo "✅ Both approaches completed!"
echo ""
echo "📊 Results saved to:"
echo "   - results/          (Original)"
echo "   - results_direct/   (Direct)"
echo ""

# Find result files to compare
if [ -n "$SITE_ID" ]; then
    CONFIG_NAME=$(basename "$CONFIG_FILE" .json)
    ORIGINAL_RESULT="results/${CONFIG_NAME}_${SITE_ID}.json"
    DIRECT_RESULT="results_direct/${CONFIG_NAME}_${SITE_ID}.json"

    if [ -f "$ORIGINAL_RESULT" ] && [ -f "$DIRECT_RESULT" ]; then
        echo "🔍 Running comparison..."
        echo ""
        python scraper_cli_direct.py compare "$ORIGINAL_RESULT" "$DIRECT_RESULT"
    fi
fi

echo ""
echo "💡 Next steps:"
echo "   1. Review accuracy of both extractions"
echo "   2. Check completeness (number of records)"
echo "   3. Note execution time (shown above)"
echo "   4. Repeat weekly to test stability"
