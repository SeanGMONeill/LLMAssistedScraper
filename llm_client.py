import json
from copy import deepcopy
from openai import OpenAI

class LLMClient:
    def __init__(self, api_key, model="o4-mini-2025-04-16"):
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def extract_details(self, markdown_text, schema):
        # Work on a copy so we don't mutate schema.prompt
        messages = deepcopy(schema.prompt)
        messages[-1]["content"] += f"\n\n{markdown_text}"

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages
        )

        content = response.choices[0].message.content.strip()
        content = content.replace("```json", "").replace("```", "")

        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            print("Failed to parse response as JSON:")
            print(content)
            result = {}

        print("Extracted:", result)
        with open("mock_llm_response.json", "w") as f:
            json.dump(result, f)

        return result

    def mocked_extract_details(self, *_):
        with open("mock_llm_response.json", "r") as f:
            return json.load(f)
