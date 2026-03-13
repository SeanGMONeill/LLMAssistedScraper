"""
Anthropic API client for direct extraction using Claude models.
"""
import json
from copy import deepcopy
from anthropic import Anthropic


class AnthropicClient:
    def __init__(self, api_key, model="claude-haiku-4-5-20251001"):
        """
        Initialize Anthropic client.

        Args:
            api_key: Anthropic API key
            model: Model to use (default: claude-haiku-4-5-20251001)
        """
        self.client = Anthropic(api_key=api_key, max_retries=5)
        self.model = model

    def extract_data(self, markdown_text, schema):
        """
        Extract structured data directly from markdown using Claude.

        Args:
            markdown_text: HTML converted to markdown
            schema: Schema object with field definitions and prompt

        Returns:
            List of extracted records as dictionaries
        """
        # Build the extraction prompt
        messages = deepcopy(schema.prompt)

        # Append the page content
        messages[-1]["content"] += f"\n\n{markdown_text}"

        # Convert to Anthropic format (only user/assistant roles)
        # If first message is system, extract it
        system_message = None
        if messages and messages[0].get("role") == "system":
            system_message = messages[0]["content"]
            messages = messages[1:]

        # Call Claude
        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,

            system=system_message if system_message else "You are a helpful assistant that extracts structured data from web pages.",
            messages=messages
        )

        # Extract text content
        content = response.content[0].text.strip()

        # Remove markdown code blocks if present
        content = content.replace("```json", "").replace("```", "").strip()

        try:
            result = json.loads(content)

            # Ensure result has the expected format
            if "extracted_data" in result:
                return result["extracted_data"]
            elif isinstance(result, list):
                return result
            else:
                print(f"Unexpected result format: {result}")
                return []

        except json.JSONDecodeError as e:
            print(f"Failed to parse Claude response as JSON: {e}")
            print(f"Response content: {content}")
            return []

    def extract_cast_info(self, page_text, show_name):
        """
        Extract cast information from page text for a given show.

        Args:
            page_text: Page content as markdown/text
            show_name: Name of the show (for context)

        Returns:
            List of {"role": str, "actor": str} dicts
        """
        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,

            system=(
                "You are an expert at extracting theatre cast lists from web pages. "
                "Return ONLY a JSON array of objects with 'role' and 'actor' keys. "
                "No markdown, no explanation, just the JSON array.\n\n"
                "Extraction rules:\n"
                "- Include every performer listed on the page without exception: principals, "
                "understudies, alternates, ensemble members, and swings.\n"
                "- If an actor is listed without a character name, use '(Billed by name only)' as their role.\n\n"
                "Normalisation rules:\n"
                "- Actor names: convert ALL CAPS names to Title Case (e.g. 'JOHN SMITH' → 'John Smith'). "
                "Preserve intentional mixed-case stylisations (e.g. 'van den Berg').\n"
                "- Role names: if an actor plays multiple roles or has multiple responsibilities, "
                "join them with ' / ' (e.g. 'Swing, Dance Captain' → 'Swing / Dance Captain', "
                "'Lafayette & Jefferson' → 'Lafayette / Jefferson'). "
                "Keep one entry per actor — do not create separate rows for each role."
            ),
            messages=[{
                "role": "user",
                "content": (
                    f"Extract the cast list for '{show_name}' from this page. "
                    f"Return a JSON array like: "
                    f'[{{"role": "Character Name", "actor": "Actor Name"}}, ...]\n\n'
                    f"{page_text}"
                )
            }]
        )

        content = response.content[0].text.strip()
        content = content.replace("```json", "").replace("```", "").strip()

        # Try to extract just the JSON array if there's extra text
        import re
        match = re.search(r'\[.*\]', content, re.DOTALL)
        if match:
            content = match.group(0)

        try:
            result = json.loads(content)
            if isinstance(result, list):
                return result
            if "cast" in result:
                return result["cast"]
            print(f"Unexpected result format: {result}")
            return []
        except json.JSONDecodeError as e:
            print(f"Failed to parse Claude response as JSON: {e}")
            print(f"Response content: {content}")
            return []
