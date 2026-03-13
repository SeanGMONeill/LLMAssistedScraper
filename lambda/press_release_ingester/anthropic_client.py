"""
Anthropic API client for press release ingestion.
Stage 1: Filter headlines to find cast-related articles.
Stage 2: Extract cast + production metadata from article text.
"""
import json
import re
from anthropic import Anthropic


class PressReleaseAnthropicClient:
    def __init__(self, api_key, model="claude-haiku-4-5-20251001"):
        self.client = Anthropic(api_key=api_key, max_retries=5)
        self.model = model

    def filter_headlines(self, articles: list[dict], source_name: str) -> list[str]:
        """
        Stage 1: Given a list of {url, headline, date} objects, return the URLs
        that are likely to contain UK theatre cast announcements.

        Favours recall over precision — missing a cast article is worse than
        fetching a non-cast one.

        Args:
            articles: List of {"url": str, "headline": str, "date": str} dicts
            source_name: Human-readable source name for context

        Returns:
            List of URLs to fetch and process
        """
        if not articles:
            return []

        articles_text = "\n".join(
            f"- URL: {a['url']} | Headline: {a.get('headline', '(no headline)')} | Date: {a.get('date', 'unknown')}"
            for a in articles
        )

        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=(
                "You are helping to identify UK theatre press releases that announce cast members. "
                "Given a list of article headlines from a theatre production company or venue, "
                "identify which are likely to contain cast information.\n\n"
                "Include articles about:\n"
                "- Cast announcements (new, additional, replacement casting)\n"
                "- Joining cast, leaving cast\n"
                "- Full or partial cast reveals for any UK production\n"
                "- Named actor announcements for shows\n"
                "- West End, touring, regional, or fringe productions\n\n"
                "Exclude: general news, award nominations without cast lists, design/creative team only, "
                "ticket sales, general show info without specific actor names, venue news, "
                "financial/business news.\n\n"
                "IMPORTANT: Favour recall over precision. When in doubt, include the URL. "
                "Return ONLY a JSON array of URL strings. No explanation, no markdown."
            ),
            messages=[{
                "role": "user",
                "content": (
                    f"Source: {source_name}\n\n"
                    f"Articles:\n{articles_text}\n\n"
                    f"Return a JSON array of URLs that likely contain UK theatre cast announcements."
                )
            }]
        )

        content = response.content[0].text.strip()
        content = content.replace("```json", "").replace("```", "").strip()

        match = re.search(r'\[.*\]', content, re.DOTALL)
        if match:
            content = match.group(0)

        try:
            result = json.loads(content)
            if isinstance(result, list):
                return [str(u) for u in result]
            return []
        except json.JSONDecodeError as e:
            print(f"Failed to parse filter_headlines response as JSON: {e}")
            print(f"Response: {content[:500]}")
            return []

    def extract_cast_from_article(self, article_text: str, source_name: str, article_url: str) -> dict:
        """
        Stage 2: Extract structured cast and production data from a press release article.

        Args:
            article_text: Plain text content of the article
            source_name: Source name for context
            article_url: URL for logging

        Returns:
            {
                "show_name": str | None,
                "show_type": "residency" | "touring" | "limited_run" | "concert" | "workshop" | None,
                "production_label": str | None,   # e.g. "West End", "UK Tour 2026"
                "production_company": str | None,
                "theatre": str | None,             # for residency/limited_run
                "city": str | None,
                "tour_legs": [{"venue": str, "city": str, "start_date": str, "end_date": str}],
                "cast": [{"role": str, "actor": str}],
                "article_date": str | None,        # YYYY-MM-DD
                "is_partial_cast": bool,
                "confidence": "high" | "medium" | "low"
            }
        """
        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=(
                "You are an expert at extracting UK theatre cast information from press releases. "
                "Return ONLY a JSON object with exactly these fields:\n"
                "- show_name: string (the production's show name, or null if unclear)\n"
                "- show_type: one of \"residency\", \"touring\", \"limited_run\", \"concert\", \"workshop\", or null\n"
                "  (residency = fixed venue indefinitely; touring = multiple venues; limited_run = fixed venue, defined run)\n"
                "- production_label: string describing this specific production, e.g. \"West End\", \"UK Tour 2026\", "
                "\"National Theatre 2026\", or null\n"
                "- production_company: the producing company/companies, or null if not mentioned\n"
                "- theatre: string (venue name for residency/limited_run), or null for touring/unknown\n"
                "- city: string (city for residency/limited_run), or null for touring/unknown\n"
                "- tour_legs: array of {\"venue\": string, \"city\": string, \"start_date\": \"YYYY-MM-DD\", \"end_date\": \"YYYY-MM-DD\"} "
                "objects for touring productions (empty array if not touring or dates not given)\n"
                "- cast: array of {\"role\": string, \"actor\": string} objects\n"
                "- article_date: string in YYYY-MM-DD format (from the article text), or null\n"
                "- is_partial_cast: boolean (true if article is about specific additions/changes rather than full cast)\n"
                "- confidence: \"high\", \"medium\", or \"low\"\n\n"
                "Rules:\n"
                "- is_partial_cast = true when the article mentions 'joining', 'additional casting', "
                "'replacing', 'will play', 'announced today', cast change, or covers only some actors\n"
                "- is_partial_cast = false only when it reads as a definitive full cast list\n"
                "- For roles: if actor plays multiple roles, join with ' / '\n"
                "- For actor names: convert ALL CAPS to Title Case\n"
                "- Include every named performer; omit creative/production staff (directors, choreographers)\n"
                "- confidence = 'high' if show name and multiple actors are clear; 'low' if uncertain\n"
                "- Return empty cast array if no cast info found\n"
                "- Return empty tour_legs array if show is not touring or no venues/dates are mentioned\n"
                "No markdown, no explanation — just the JSON object."
            ),
            messages=[{
                "role": "user",
                "content": (
                    f"Source: {source_name}\n"
                    f"URL: {article_url}\n\n"
                    f"Article text:\n{article_text[:8000]}"
                )
            }]
        )

        content = response.content[0].text.strip()
        content = content.replace("```json", "").replace("```", "").strip()

        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            content = match.group(0)

        try:
            result = json.loads(content)
            return {
                "show_name": result.get("show_name"),
                "show_type": result.get("show_type"),
                "production_label": result.get("production_label"),
                "production_company": result.get("production_company"),
                "theatre": result.get("theatre"),
                "city": result.get("city"),
                "tour_legs": result.get("tour_legs") or [],
                "cast": result.get("cast", []),
                "article_date": result.get("article_date"),
                "is_partial_cast": bool(result.get("is_partial_cast", True)),
                "confidence": result.get("confidence", "low")
            }
        except json.JSONDecodeError as e:
            print(f"Failed to parse extract_cast_from_article response: {e}")
            print(f"Response: {content[:500]}")
            return {
                "show_name": None,
                "show_type": None,
                "production_label": None,
                "production_company": None,
                "theatre": None,
                "city": None,
                "tour_legs": [],
                "cast": [],
                "article_date": None,
                "is_partial_cast": True,
                "confidence": "low"
            }
