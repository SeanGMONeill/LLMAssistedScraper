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
        self.client = Anthropic(api_key=api_key)
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
