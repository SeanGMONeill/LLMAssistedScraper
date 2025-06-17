import json

class Schema:
    def __init__(self, prompt, attributes):
        self.prompt = self._flatten_prompt(prompt)
        self.attributes = attributes

    @classmethod
    def from_file(cls, path):
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return cls(prompt=data["prompt"], attributes=data["attributes"])

    def _flatten_prompt(self, prompt):
        flat_prompt = []
        for message in prompt:
            content = (
                message["content"]
                if isinstance(message["content"], str)
                else "".join(message["content"])
            )
            flat_prompt.append({
                "role": message["role"],
                "content": content
            })
        return flat_prompt

    def __repr__(self):
        return f"<Schema attributes={self.attributes}>"
