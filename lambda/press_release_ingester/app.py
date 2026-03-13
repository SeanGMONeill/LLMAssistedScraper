"""
Lambda function for ingesting West End press releases.
Fetches news index pages, filters for cast announcements, extracts cast data,
and writes results to DynamoDB (ScrapesTable) + dedup table (PressReleasesTable).

Trigger: EventBridge daily at 07:00 UTC  OR  manual invoke.
Payload:
  {}                          — normal mode (page 1 only)
  {"backfill": true}          — backfill mode (all pages, stop when all known)
  {"backfill": true, "dry_run": true}  — log only, write nothing
"""

import hashlib
import json
import os
import re
import traceback
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

import boto3
import html2text
import requests
from bs4 import BeautifulSoup

from anthropic_client import PressReleaseAnthropicClient
from resolver import resolve_production

# ---------------------------------------------------------------------------
# AWS clients
# ---------------------------------------------------------------------------
dynamodb = boto3.resource('dynamodb')
s3 = boto3.client('s3')
secretsmanager = boto3.client('secretsmanager')
sns = boto3.client('sns')

# ---------------------------------------------------------------------------
# Environment variables
# ---------------------------------------------------------------------------
PRESS_RELEASES_TABLE = os.environ['PRESS_RELEASES_TABLE']
SCRAPES_TABLE = os.environ['SCRAPES_TABLE']
SHOW_INDEX_TABLE = os.environ['SHOW_INDEX_TABLE']
PRESS_RELEASE_CONTENT_BUCKET = os.environ['PRESS_RELEASE_CONTENT_BUCKET']
SITES_CONFIG_S3_BUCKET = os.environ['SITES_CONFIG_S3_BUCKET']
PRESS_RELEASE_SOURCES_S3_KEY = os.environ.get('PRESS_RELEASE_SOURCES_S3_KEY', 'press_release_sources.json')
SHOWS_CONFIG_S3_KEY = os.environ.get('SHOWS_CONFIG_S3_KEY', 'shows.json')
ANTHROPIC_API_KEY_SECRET = os.environ['ANTHROPIC_API_KEY_SECRET']
ALERT_TOPIC_ARN = os.environ['ALERT_TOPIC_ARN']
ENVIRONMENT = os.environ['ENVIRONMENT']

# ---------------------------------------------------------------------------
# Cached API key
# ---------------------------------------------------------------------------
_anthropic_api_key = None


def get_anthropic_api_key() -> str:
    global _anthropic_api_key
    if _anthropic_api_key is None:
        response = secretsmanager.get_secret_value(SecretId=ANTHROPIC_API_KEY_SECRET)
        _anthropic_api_key = response['SecretString']
    return _anthropic_api_key


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
REQUEST_TIMEOUT = 30
HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    )
}


def fetch_page(url: str, ssl_verify: bool = True) -> str | None:
    """Fetch a URL, return HTML string or None on failure."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, verify=ssl_verify)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"Failed to fetch {url}: {e}")
        return None


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_sources_config() -> list[dict]:
    """Load press release sources from S3."""
    response = s3.get_object(Bucket=SITES_CONFIG_S3_BUCKET, Key=PRESS_RELEASE_SOURCES_S3_KEY)
    config = json.loads(response['Body'].read().decode('utf-8'))
    return [s for s in config.get('sources', []) if s.get('enabled', True)]


def load_shows_config() -> list[dict]:
    """Load show aliases config from S3 (for resolver)."""
    response = s3.get_object(Bucket=SITES_CONFIG_S3_BUCKET, Key=SHOWS_CONFIG_S3_KEY)
    config = json.loads(response['Body'].read().decode('utf-8'))
    return config.get('shows', [])


# ---------------------------------------------------------------------------
# Headline parsing
# ---------------------------------------------------------------------------

def build_index_url(source: dict, page: int) -> str:
    """Build news index URL for a given page number."""
    base_url = source['news_index_url']
    pagination = source.get('pagination', {})
    ptype = pagination.get('type', 'query_param')

    if ptype == 'query_param':
        param = pagination.get('param', 'page')
        start = pagination.get('start', 1)
        if page == start:
            return base_url  # page 1 — no param needed
        return f"{base_url}?{param}={page}"
    elif ptype == 'path':
        param = pagination.get('param', 'page')
        start = pagination.get('start', 1)
        if page == start:
            return base_url
        return f"{base_url}/{param}/{page}"
    else:
        return base_url


def _make_absolute(href: str, base_url: str) -> str:
    """Convert a relative href to an absolute URL."""
    from urllib.parse import urlparse, urljoin
    if href.startswith('http'):
        return href
    return urljoin(base_url, href)


def parse_headlines(html: str, base_url: str) -> list[dict]:
    """
    Parse a news index page and return [{url, headline, date}] dicts.

    Strategy:
    1. Try structured article containers (<article>, news <li>s).
    2. Fall back to extracting all links that look like individual article URLs
       (contain /news/, /press/, /article/, or a year-like path segment).
    """
    from urllib.parse import urlparse
    soup = BeautifulSoup(html, 'html.parser')
    base_domain = urlparse(base_url).netloc
    articles = []
    seen_urls = set()

    def add_article(href, headline, date_str=''):
        href = _make_absolute(href, base_url)
        # Only follow links on the same domain
        if urlparse(href).netloc != base_domain:
            return
        if href in seen_urls or href == base_url.rstrip('/'):
            return
        if len(headline) < 5:
            return
        seen_urls.add(href)
        articles.append({
            'url': href,
            'headline': headline[:200],
            'date': date_str[:20] if date_str else ''
        })

    # --- Strategy 1: structured containers ---
    containers = (
        soup.find_all('article') +
        soup.find_all('li', class_=lambda c: c and any(
            kw in c.lower() for kw in ('news', 'post', 'article', 'item', 'card', 'entry')
        ))
    )

    for container in containers:
        link = container.find('a', href=True)
        if not link:
            continue
        heading = container.find(['h1', 'h2', 'h3', 'h4'])
        headline = heading.get_text(strip=True) if heading else link.get_text(strip=True)
        date_el = container.find('time')
        date_str = date_el.get('datetime', date_el.get_text(strip=True)) if date_el else ''
        add_article(link['href'], headline, date_str)

    # --- Strategy 2: fallback — all heading-anchored links ---
    if len(articles) <= 1:
        for heading in soup.find_all(['h1', 'h2', 'h3', 'h4']):
            link = heading.find('a', href=True) or heading.find_parent('a')
            if not link:
                # Look for nearest sibling/parent link
                parent = heading.parent
                link = parent.find('a', href=True) if parent else None
            if not link:
                continue
            headline = heading.get_text(strip=True)
            # Look for nearby date
            date_str = ''
            container = heading.parent
            if container:
                date_el = container.find('time')
                date_str = date_el.get('datetime', date_el.get_text(strip=True)) if date_el else ''
            add_article(link['href'], headline, date_str)

    # --- Strategy 3: last resort — any link whose URL path looks like an article ---
    if len(articles) <= 1:
        article_path_pattern = re.compile(
            r'/(news|press|article|release|story|post|update)/|/\d{4}/\d{2}/',
            re.IGNORECASE
        )
        for link in soup.find_all('a', href=True):
            href = _make_absolute(link['href'], base_url)
            if not article_path_pattern.search(href):
                continue
            headline = link.get_text(strip=True)
            add_article(link['href'], headline)

    print(f"Parsed {len(articles)} headlines from {base_url}")
    return articles


def fetch_articles_from_sitemap(sitemap_url: str, ssl_verify: bool = True) -> list[dict]:
    """
    Fetch article list from an XML sitemap.
    Returns [{url, headline (from slug), date (lastmod)}] dicts.
    Sitemap pagination (sitemapindex) is followed automatically.
    """
    articles = []

    def parse_sitemap(url: str):
        html = fetch_page(url, ssl_verify=ssl_verify)
        if not html:
            return
        try:
            root = ET.fromstring(html)
        except ET.ParseError as e:
            print(f"Failed to parse sitemap XML from {url}: {e}")
            return

        ns = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}

        # Sitemap index — recurse into child sitemaps
        for sitemap_el in root.findall('sm:sitemap', ns):
            loc = sitemap_el.findtext('sm:loc', namespaces=ns)
            if loc:
                parse_sitemap(loc)

        # Regular urlset
        for url_el in root.findall('sm:url', ns):
            loc = url_el.findtext('sm:loc', namespaces=ns)
            lastmod = url_el.findtext('sm:lastmod', namespaces=ns) or ''
            if not loc:
                continue
            # Derive a headline from the URL slug (last path segment, de-slugified)
            slug = loc.rstrip('/').split('/')[-1]
            slug = slug.split('?')[0]  # strip query params
            headline = slug.replace('-', ' ').replace('_', ' ')[:200]
            # Normalise lastmod to YYYY-MM-DD
            date_str = lastmod[:10] if lastmod else ''
            articles.append({'url': loc, 'headline': headline, 'date': date_str})

    parse_sitemap(sitemap_url)
    print(f"Loaded {len(articles)} URLs from sitemap {sitemap_url}")
    return articles


# ---------------------------------------------------------------------------
# DynamoDB dedup
# ---------------------------------------------------------------------------

def url_hash(url: str) -> str:
    return hashlib.md5(url.encode('utf-8')).hexdigest()


def already_processed(domain: str, article_url: str) -> bool:
    """Return True if this article has already been processed."""
    table = dynamodb.Table(PRESS_RELEASES_TABLE)
    response = table.get_item(
        Key={
            'PK': f"SOURCE#{domain}",
            'SK': f"ARTICLE#{url_hash(article_url)}"
        }
    )
    return 'Item' in response


def write_press_release_record(domain: str, article_url: str, result: dict, s3_key: str | None) -> None:
    """Write dedup record to PressReleasesTable."""
    table = dynamodb.Table(PRESS_RELEASES_TABLE)
    now = datetime.now(timezone.utc).isoformat()

    item = {
        'PK': f"SOURCE#{domain}",
        'SK': f"ARTICLE#{url_hash(article_url)}",
        'url': article_url,
        'processed_at': now,
        'contained_cast': bool(result.get('cast')),
        'shows_extracted': [result['show_name']] if result.get('show_name') else []
    }
    if result.get('article_date'):
        item['article_date'] = result['article_date']
    if s3_key:
        item['s3_key'] = s3_key

    table.put_item(Item=item)


# ---------------------------------------------------------------------------
# S3 raw storage
# ---------------------------------------------------------------------------

def store_article_html(html: str, source_id: str, article_url: str) -> str:
    """Store raw article HTML in S3, return the S3 key."""
    now = datetime.now(timezone.utc)
    year = now.strftime('%Y')
    month = now.strftime('%m')
    h = url_hash(article_url)
    key = f"press-releases/{source_id}/{year}/{month}/{h}.html"

    s3.put_object(
        Bucket=PRESS_RELEASE_CONTENT_BUCKET,
        Key=key,
        Body=html.encode('utf-8'),
        ContentType='text/html'
    )
    print(f"Stored article HTML at s3://{PRESS_RELEASE_CONTENT_BUCKET}/{key}")
    return key


# ---------------------------------------------------------------------------
# DynamoDB — scrapes table write
# ---------------------------------------------------------------------------

def write_to_scrapes_table(
    result: dict,
    article_url: str,
    production_id: str,
    show_slug: str,
    canonical_name: str,
    source_production_company: str | None,
) -> None:
    """
    Write a press-release-sourced cast extraction to ScrapesTable.
    Uses article_date as the effective date (not ingestion timestamp).
    PK = PRODUCTION#{production_id}
    """
    table = dynamodb.Table(SCRAPES_TABLE)

    article_date = result.get('article_date') or datetime.now(timezone.utc).strftime('%Y-%m-%d')
    scraped_at = f"{article_date}T00:00:00+00:00"

    item = {
        'PK': f"PRODUCTION#{production_id}",
        'SK': f"SCRAPE#{scraped_at}#{url_hash(article_url)}",
        'date_key': f"DATE#{article_date}",
        'production_id': production_id,
        'show_name': canonical_name,
        'show_slug': show_slug,
        'source_url': article_url,
        'scraped_at': scraped_at,
        'scrape_status': 'success',
        'cast': result['cast'],
        'cast_count': len(result['cast']),
        'source_type': 'press_release',
        'article_date': article_date,
        'is_partial_cast': result.get('is_partial_cast', True),
        'production_company': source_production_company or result.get('production_company'),
        'scraper_version': '1.0.0'
    }
    for field in ('production_label', 'show_type', 'theatre', 'city'):
        if result.get(field):
            item[field] = result[field]

    item = {k: v for k, v in item.items() if v is not None}

    table.put_item(Item=item)
    print(f"Wrote press release scrape: {item['PK']} / {item['SK']}")

    # Future: SNS fan-out here for parallel processing


def write_show_production_summary(
    production_id: str,
    show_slug: str,
    canonical_name: str,
    result: dict,
    article_url: str,
    source_production_company: str | None,
    article_date: str,
) -> None:
    """
    Write SHOW#{show_slug}/PRODUCTION#{production_id} summary to ShowIndex.
    Only written when resolver determines this is a new production.
    Skipped if a scrape-sourced summary already exists.
    """
    table = dynamodb.Table(SHOW_INDEX_TABLE)
    try:
        resp = table.get_item(Key={
            'PK': f"SHOW#{show_slug}",
            'SK': f"PRODUCTION#{production_id}"
        })
        existing = resp.get('Item')
        if existing and existing.get('data_source') == 'scrape':
            print(f"[resolver] SHOW# summary already scrape-sourced, skipping press release write")
            return
    except Exception as e:
        print(f"Error checking existing SHOW# summary: {e}")

    summary = {
        'PK': f"SHOW#{show_slug}",
        'SK': f"PRODUCTION#{production_id}",
        'production_id': production_id,
        'show_name': canonical_name,
        'show_slug': show_slug,
        'cast_count': len(result.get('cast', [])),
        'last_updated': article_date,
        'data_source': 'press_release',
        'needs_review': True,
        'source_url': article_url,
        'production_company': source_production_company or result.get('production_company'),
    }
    for field in ('production_label', 'show_type', 'theatre', 'city'):
        if result.get(field):
            summary[field] = result[field]

    summary = {k: v for k, v in summary.items() if v is not None}
    table.put_item(Item=summary)
    print(f"Wrote SHOW# summary for new production: {production_id}")


# ---------------------------------------------------------------------------
# html2text conversion
# ---------------------------------------------------------------------------

def html_to_text(html: str) -> str:
    converter = html2text.HTML2Text()
    converter.ignore_links = True
    converter.ignore_images = True
    converter.body_width = 0
    return converter.handle(html)


# ---------------------------------------------------------------------------
# Alert
# ---------------------------------------------------------------------------

def send_alert(subject: str, message: str) -> None:
    try:
        sns.publish(
            TopicArn=ALERT_TOPIC_ARN,
            Subject=f"[{ENVIRONMENT.upper()}] {subject}",
            Message=message
        )
    except Exception as e:
        print(f"Failed to send alert: {e}")


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------

def lambda_handler(event, context):
    """
    Lambda handler for press release ingestion.

    Event:
      {}                                    — normal mode
      {"backfill": true}                    — paginate all pages
      {"backfill": true, "dry_run": true}   — log only, no writes
    """
    backfill_mode = bool(event.get('backfill', False))
    dry_run = bool(event.get('dry_run', False))
    max_pages_override = event.get('max_pages_override')  # int — caps pages regardless of config

    print(f"Press release ingester starting — backfill={backfill_mode}, dry_run={dry_run}")

    try:
        sources = load_sources_config()
        shows_config = load_shows_config()
    except Exception as e:
        print(f"Failed to load config from S3: {e}")
        send_alert("Press Release Ingester — Config Load Failed", str(e))
        raise

    show_index_table = dynamodb.Table(SHOW_INDEX_TABLE)
    api_key = get_anthropic_api_key()
    llm = PressReleaseAnthropicClient(api_key=api_key)

    summary = {
        'sources_processed': 0,
        'articles_seen': 0,
        'articles_new': 0,
        'articles_with_cast': 0,
        'dry_run': dry_run
    }

    for source in sources:
        source_id = source['id']
        source_name = source['name']
        domain = source['domain']
        pagination = source.get('pagination', {})
        start_page = pagination.get('start', 1)
        config_max = pagination.get('max_pages', 50) if backfill_mode else start_page
        max_pages = min(config_max, int(max_pages_override)) if max_pages_override else config_max

        print(f"--- Processing source: {source_name} ---")
        summary['sources_processed'] += 1

        ssl_verify = source.get('ssl_verify', True)
        fetch_type = source.get('fetch_type', 'html_index')  # 'html_index' | 'sitemap'

        # ------------------------------------------------------------------
        # Build the candidate article list (Stage 0)
        # ------------------------------------------------------------------
        if fetch_type == 'sitemap':
            sitemap_url = source.get('sitemap_url')
            if not sitemap_url:
                print(f"  No sitemap_url configured for {source_name}, skipping")
                continue
            all_articles = fetch_articles_from_sitemap(sitemap_url, ssl_verify=ssl_verify)
            # In normal mode (not backfill), only look at articles from the last 2 days
            if not backfill_mode:
                from datetime import timedelta
                cutoff = (datetime.now(timezone.utc) - timedelta(days=2)).strftime('%Y-%m-%d')
                all_articles = [a for a in all_articles if a.get('date', '') >= cutoff]
                print(f"  Normal mode: filtered to {len(all_articles)} articles from last 2 days")
            summary['articles_seen'] += len(all_articles)

            # Keyword pre-filter before LLM — keeps only plausible cast-news slugs
            cast_keywords = re.compile(
                r'cast|join|announce|casting|role|star|play|lead|named|reveal|debut|'
                r'first look|new look|west end|ensemble|principal|heading',
                re.IGNORECASE
            )
            pre_filtered = [a for a in all_articles if cast_keywords.search(a.get('headline', ''))]
            print(f"  Keyword pre-filter: {len(all_articles)} → {len(pre_filtered)} articles")

            # Stage 1 LLM filter in batches of 50
            flagged_urls = []
            batch_size = 50
            for i in range(0, len(pre_filtered), batch_size):
                batch = pre_filtered[i:i + batch_size]
                batch_flagged = llm.filter_headlines(batch, source_name)
                flagged_urls.extend(batch_flagged)
                print(f"  LLM batch {i//batch_size + 1}: {len(batch)} → {len(batch_flagged)} flagged")

            print(f"Sitemap: {len(all_articles)} total, {len(pre_filtered)} pre-filtered, {len(flagged_urls)} flagged by LLM")

            # Dedup
            new_urls = [u for u in flagged_urls if not already_processed(domain, u)]
            summary['articles_new'] += len(new_urls)

            if dry_run:
                print(f"[dry_run] Would fetch and extract {len(new_urls)} articles")
                new_urls = []  # skip Stage 2 in dry_run

        else:
            # html_index: paginate through news index pages
            new_urls = []
            page = start_page
            while page <= max_pages:
                index_url = build_index_url(source, page)
                print(f"Fetching index page {page}: {index_url}")

                html = fetch_page(index_url, ssl_verify=ssl_verify)
                if not html:
                    print(f"Could not fetch index page for {source_name} page {page}, stopping")
                    break

                articles = parse_headlines(html, index_url)
                if not articles:
                    print(f"No articles found on page {page} for {source_name}, stopping")
                    break

                summary['articles_seen'] += len(articles)

                if dry_run:
                    flagged_urls = [a['url'] for a in articles]
                    print(f"[dry_run] Would filter {len(articles)} headlines via LLM")
                else:
                    flagged_urls = llm.filter_headlines(articles, source_name)

                print(f"Page {page}: {len(articles)} articles, {len(flagged_urls)} flagged by LLM")

                page_new = []
                all_known = True
                for url in flagged_urls:
                    if already_processed(domain, url):
                        print(f"  [skip] Already processed: {url}")
                    else:
                        page_new.append(url)
                        all_known = False

                new_urls.extend(page_new)
                summary['articles_new'] += len(page_new)

                if backfill_mode and all_known and len(flagged_urls) > 0:
                    print(f"All flagged URLs on page {page} already known — stopping backfill for {source_name}")
                    break

                if not backfill_mode:
                    break

                page += 1

            if dry_run:
                print(f"[dry_run] Would fetch and extract {len(new_urls)} articles")
                new_urls = []  # skip Stage 2 in dry_run

        # ------------------------------------------------------------------
        # Stage 2: Fetch + extract each new article
        # ------------------------------------------------------------------
        for article_url in new_urls:
            print(f"  Processing article: {article_url}")
            try:
                article_html = fetch_page(article_url, ssl_verify=ssl_verify)
                if not article_html:
                    print(f"  Could not fetch article: {article_url}")
                    if not dry_run:
                        write_press_release_record(domain, article_url, {'cast': []}, None)
                    continue

                s3_key = None
                if not dry_run:
                    s3_key = store_article_html(article_html, source_id, article_url)

                article_text = html_to_text(article_html)

                if dry_run:
                    print(f"  [dry_run] Would call LLM to extract cast from {len(article_text)} chars")
                    result = {'show_name': None, 'cast': [], 'article_date': None, 'is_partial_cast': True, 'confidence': 'low'}
                else:
                    result = llm.extract_cast_from_article(article_text, source_name, article_url)

                print(f"  Extracted: show={result.get('show_name')}, cast={len(result.get('cast', []))}, "
                      f"partial={result.get('is_partial_cast')}, confidence={result.get('confidence')}")

                if result.get('cast') and result.get('show_name') and result.get('confidence') != 'low':
                    summary['articles_with_cast'] += 1
                    if not dry_run:
                        # Resolve to a stable production_id
                        production_id, show_slug, canonical_name, is_new = resolve_production(
                            show_name=result['show_name'],
                            show_type=result.get('show_type'),
                            production_label=result.get('production_label'),
                            theatre=result.get('theatre'),
                            city=result.get('city'),
                            article_date=result.get('article_date'),
                            show_index_table=show_index_table,
                            shows_config=shows_config,
                        )
                        source_production_company = source.get('production_company')
                        article_date = result.get('article_date') or datetime.now(timezone.utc).strftime('%Y-%m-%d')

                        write_to_scrapes_table(
                            result, article_url,
                            production_id, show_slug, canonical_name, source_production_company,
                        )
                        if is_new:
                            write_show_production_summary(
                                production_id, show_slug, canonical_name,
                                result, article_url, source_production_company, article_date,
                            )

                if not dry_run:
                    write_press_release_record(domain, article_url, result, s3_key)

            except Exception as e:
                print(f"  Error processing article {article_url}: {e}")
                traceback.print_exc()
                if not dry_run:
                    try:
                        write_press_release_record(domain, article_url, {'cast': []}, None)
                    except Exception:
                        pass

    print(f"Press release ingester complete: {json.dumps(summary)}")

    return {
        'statusCode': 200,
        'body': json.dumps(summary)
    }
