"""
Turns a Pydantic model into a JSON schema that strict structured-output
modes accept (e.g. Groq's `strict: true`).

Strict modes require:
  - every object to list ALL its properties as required,
  - `additionalProperties: false` on every object,
  - no references ($ref) — so definitions are copied inline.

Validation keywords such as minLength or maxItems are removed here, because
not every provider supports them. That is safe: the gateway always checks
the reply against the full Pydantic model afterwards.
"""
from typing import Any

from pydantic import BaseModel

# Keywords removed from the schema sent to the provider (Pydantic still enforces them).
_DROPPED_KEYWORDS = {
    "title", "default", "minLength", "maxLength", "minItems", "maxItems",
    "pattern", "format", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
}


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """The provider-facing JSON schema for `model`."""
    schema = model.model_json_schema()
    definitions = schema.pop("$defs", {})
    return _clean(schema, definitions)


def _clean(node: Any, definitions: dict[str, Any]) -> Any:
    if isinstance(node, list):
        return [_clean(item, definitions) for item in node]
    if not isinstance(node, dict):
        return node

    if "$ref" in node:
        name = node["$ref"].split("/")[-1]
        return _clean(definitions[name], definitions)

    cleaned = {
        key: _clean(value, definitions)
        for key, value in node.items()
        if key not in _DROPPED_KEYWORDS
    }
    if cleaned.get("type") == "object" and "properties" in cleaned:
        cleaned["required"] = list(cleaned["properties"].keys())
        cleaned["additionalProperties"] = False
    return cleaned
