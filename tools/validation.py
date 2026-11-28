"""Dependency-free validator for the JSON Schema subset used by registered tools."""

import math


def validate(value, schema, path="$"):
    kind = schema.get("type")
    types = {
        "object": dict,
        "array": list,
        "string": str,
        "boolean": bool,
        "null": type(None),
        "integer": int,
        "number": (int, float),
    }
    if kind and (
        kind not in types
        or not isinstance(value, types[kind])
        or kind in {"integer", "number"}
        and isinstance(value, bool)
    ):
        raise ValueError(f"{path}: expected {kind}")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{path}: non-finite number")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path}: invalid enum")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                raise ValueError(f"{path}: missing {key}")
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key in properties:
                validate(item, properties[key], path + "." + key)
            elif schema.get("additionalProperties") is False:
                raise ValueError(f"{path}: unknown {key}")
    if isinstance(value, list):
        for i, item in enumerate(value):
            validate(item, schema.get("items", {}), f"{path}[{i}]")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get(
            "maxLength", float("inf")
        ):
            raise ValueError(f"{path}: invalid length")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value < schema.get("minimum", -float("inf")) or value > schema.get(
            "maximum", float("inf")
        ):
            raise ValueError(f"{path}: out of bounds")
