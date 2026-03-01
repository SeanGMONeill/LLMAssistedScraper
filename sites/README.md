# Sites Configuration

This directory contains configuration files for scraping different types of websites.

## Files

- **west_end.json** - West End theatre cast pages (for AWS production deployment)
- **cast_lists.json** - General cast lists (legacy/dev)
- **books.json** - Book-related sites (legacy/dev)

## west_end.json Format

```json
{
  "sites": [
    {
      "name": "Show Name",
      "url": "https://example.com/cast",
      "id": "unique_identifier",
      "selectors": {
        "cast_section": "div.cast-container",
        "role_elements": "h3.role",
        "actor_elements": "p.actor"
      }
    }
  ]
}
```

### Fields

- **name** (required): Human-readable show name
- **url** (required): URL to the cast page
- **id** (required): Unique identifier (lowercase, underscores)
- **selectors** (optional): CSS selectors to help the scraper
  - If not provided, the LLM will extract cast info from the full page text
  - Helpful for complex pages or to improve accuracy

## Adding New Shows

### 1. Find the Official Cast Page

Search for "{Show Name} West End cast" and find the official website.

**Good URLs:**
- Official show website cast pages
- Theatre websites with cast listings
- Production company cast pages

**Avoid:**
- Ticketing sites (often no cast info)
- Wikipedia (not always up to date)
- Fan sites (may be outdated)

### 2. Add to west_end.json

```json
{
  "name": "New Show",
  "url": "https://newshow.com/cast",
  "id": "new_show",
  "selectors": {}
}
```

### 3. Test Locally (Optional)

```bash
# Run the scraper locally
python direct_extractor.py --url "https://newshow.com/cast"

# Or test with the full pipeline
python anthropic_client.py
```

### 4. Upload to S3

```bash
# After deployment, get the S3 bucket name
BUCKET=$(aws cloudformation describe-stacks \
  --stack-name west-end-scraper-prod \
  --query 'Stacks[0].Outputs[?OutputKey==`SitesConfigBucket`].OutputValue' \
  --output text)

# Upload updated configuration
aws s3 cp sites/west_end.json s3://${BUCKET}/west_end.json

# Verify upload
aws s3 ls s3://${BUCKET}/
```

### 5. Trigger a Test Scrape

```bash
# Get queue URL
QUEUE_URL=$(aws cloudformation describe-stacks \
  --stack-name west-end-scraper-prod \
  --query 'Stacks[0].Outputs[?OutputKey==`ScrapeJobsQueueUrl`].OutputValue' \
  --output text)

# Send test job
aws sqs send-message \
  --queue-url $QUEUE_URL \
  --message-body '{
    "show_name": "New Show",
    "url": "https://newshow.com/cast",
    "selectors": {}
  }'

# Check logs
aws logs tail /aws/lambda/west-end-scraper-prod --follow
```

## Current Shows (15)

The starter configuration includes these popular West End shows:

1. Wicked
2. Book of Mormon
3. Stranger Things: The First Shadow
4. Hamilton
5. The Lion King
6. Les Miserables
7. The Phantom of the Opera
8. Mamma Mia
9. Matilda The Musical
10. SIX
11. Moulin Rouge
12. Back to the Future
13. Chicago
14. Frozen
15. The Play That Goes Wrong

## Expanding to 50+ Shows

### Resources for Finding Shows

1. **Official London Theatre** - https://officiallondontheatre.com/
   - Complete directory of West End shows
   - Links to official websites

2. **Society of London Theatre (SOLT)**
   - Industry organization
   - Maintains official show listings

3. **Theatre websites by venue:**
   - Apollo Victoria, Lyceum Theatre, Prince Edward Theatre, etc.
   - Each venue lists current production

### Tips

- Focus on long-running shows (more stable cast pages)
- Avoid shows that are closing soon
- Some shows may not publish cast online - skip these
- Check if the cast page is regularly updated
- Test each URL before adding to production

### Maintenance

Review quarterly:
- Remove closed shows
- Add new openings
- Update URLs if websites change
- Verify cast pages are still active

## Selectors Guide

### When to Use Selectors

Use selectors when:
- The page has lots of non-cast content (ads, news, etc.)
- The cast section has a specific container
- You want to improve scraping speed/accuracy

### Finding Selectors

1. Open the cast page in a browser
2. Right-click on the cast section → Inspect
3. Find the CSS class or ID wrapping the cast list
4. Test the selector in browser console:
   ```javascript
   document.querySelectorAll('div.cast-list')
   ```

### Example Selectors

```json
{
  "selectors": {
    "cast_section": "div.cast-container",
    "role_elements": "h3.character-name",
    "actor_elements": "p.performer-name"
  }
}
```

**Note:** Selectors are optional. The LLM is quite good at extracting cast info from raw text without them.

## Troubleshooting

### Scraper Returns Empty Cast

**Possible causes:**
- Website blocks automated access (check for Cloudflare, etc.)
- Cast page requires JavaScript (Selenium should handle this)
- URL is wrong or redirects
- Cast page format is unusual

**Solutions:**
1. Test the URL manually
2. Try adding specific selectors
3. Check Lambda logs for errors
4. Consider contacting the show's production team

### Data Quality Warnings

If you receive alerts about suspicious data:

1. Check the scrape result in DynamoDB
2. Compare to previous scrape
3. Visit the website manually
4. Check if website structure changed
5. Update selectors if needed

### Website Changed

If a show's website changes:

1. Find the new cast page URL
2. Update `west_end.json`
3. Update selectors if structure changed
4. Upload to S3
5. Trigger a test scrape

## Best Practices

✅ **DO:**
- Use official show websites
- Keep URLs up to date
- Test new sites before adding to prod
- Document unusual configurations
- Remove closed shows promptly

❌ **DON'T:**
- Use ticketing/reseller sites
- Add shows without cast pages
- Hardcode dates or seasons in URLs
- Add duplicate shows
- Forget to upload changes to S3

## Version Control

This configuration is:
- Stored in Git (this repo)
- Deployed to S3 (production)

**Workflow:**
1. Edit `sites/west_end.json` locally
2. Commit to Git
3. Upload to S3
4. Changes take effect on next scheduled run

Always commit changes to Git first, then deploy to S3!
