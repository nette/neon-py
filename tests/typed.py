"""Typed values of the corpus."""

import math
from decimal import Decimal
from typing import Any

from neon import CHAIN, Date, Entity, Value


def to_host(typed: dict[str, Any]) -> Value:
    """The Python value of a typed value."""
    match typed:
        case {"type": "null"}:
            return None
        case {"type": "bool" | "string", "value": value}:
            return value
        case {"type": "int", "value": value}:
            return int(Decimal(value))
        case {"type": "float", "value": value}:
            specials = {"INF": math.inf, "-INF": -math.inf, "NAN": math.nan}
            return specials[value] if value in specials else float(value)
        case {"type": "date", "value": value}:
            date = Date.parse(value)
            if date is None:
                raise ValueError(f"Invalid date {value}")
            return date
        case {"type": "entity", "value": value, "attributes": attributes}:
            args = to_host(attributes)
            assert isinstance(args, list | dict)
            return Entity(to_host(value), args)
        case {"type": "chain", "entities": entities}:
            return Entity(CHAIN, [to_host(e) for e in entities])
        case {"type": "list", "items": items}:
            return [to_host(v) for v in items]
        case {"type": "map", "entries": entries}:
            if entries and all(key == str(i) for i, (key, _) in enumerate(entries)):
                raise ValueError("A map with keys 0..n-1 must be written as a list.")
            return {key: to_host(v) for key, v in entries}
    raise ValueError(f"Unknown type {typed.get('type')}")


def equal(a: object, b: object) -> bool:
    """Equality of the specification: types, order of entries and dates by components."""
    if type(a) is not type(b):
        return False
    if isinstance(a, float) and isinstance(b, float):
        return a == b or (math.isnan(a) and math.isnan(b))
    if isinstance(a, Entity) and isinstance(b, Entity):
        return equal(a.value, b.value) and equal(a.attributes, b.attributes)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(a, dict) and isinstance(b, dict):
        return list(a) == list(b) and all(equal(a[k], b[k]) for k in a)
    return a == b
