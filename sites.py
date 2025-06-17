import json
from schema import Schema

class Sites:
    def __init__(self, schema_path, sites, id):
        self.schema = Schema.from_file(schema_path)
        self.sites = sites
        self.id = id

    @classmethod
    def from_file(cls, path):
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return cls(id=data["id"], schema_path=data["schema"], sites=data["sites"])

    def __repr__(self):
        return f"<Sites attributes={self.attributes}>"
