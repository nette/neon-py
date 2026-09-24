from __future__ import annotations

from collections.abc import Sequence

from .nodes import Node
from .token import Token, Trivia

_SLOTS = {
    "DocumentNode": (("value", "value"), ("endOfFile", "end_of_file")),
    "BlockArrayNode": (("items", "items"),),
    "InlineArrayNode": (
        ("openBracket", "open_bracket"),
        ("items", "items"),
        ("closeBracket", "close_bracket"),
    ),
    "ArrayItemNode": (
        ("bullet", "bullet"),
        ("key", "key"),
        ("colon", "colon"),
        ("value", "value"),
        ("separator", "separator"),
    ),
    "EntityNode": (("value", "value"), ("attributes", "attributes")),
    "EntityChainNode": (("entities", "entities"),),
    "StringNode": (("token", "token"),),
    "LiteralNode": (("token", "token"),),
}

_SHORT_ESCAPES = {"\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def dump(node: Node) -> str:
    """Text form of the tree, as in the conformance corpus."""
    lines: list[str] = []

    def write(node: Node, prefix: str, depth: int) -> None:
        indent = "\t" * depth
        name = type(node).__name__
        lines.append(indent + prefix + name)
        for slot, attribute in _SLOTS[name]:
            value = getattr(node, attribute)
            if value is None:
                continue
            if isinstance(value, tuple):
                if not value:
                    lines.append(f"{indent}\t{slot}: []")
                    continue
                lines.append(f"{indent}\t{slot}:")
                for item in value:
                    write(item, "- ", depth + 2)
            elif isinstance(value, Node):
                write(value, slot + ": ", depth + 1)
            else:
                lines.append(f"{indent}\t{slot}: {dump_token(value)}")

    write(node, "", 0)
    return "\n".join(lines) + "\n"


def dump_token(token: Token) -> str:
    res = f"{token.kind} {_dump_text(token.text)}"
    if token.leading_trivia:
        res += " <" + _dump_trivia(token.leading_trivia)
    if token.trailing_trivia:
        res += " >" + _dump_trivia(token.trailing_trivia)
    return res


def _dump_trivia(trivia: Sequence[Trivia]) -> str:
    return "[" + ", ".join(f"{t.kind} {_dump_text(t.text)}" for t in trivia) + "]"


def _dump_text(text: str) -> str:
    """JSON string escaping only quotes, backslashes and control characters."""
    res = ['"']
    for c in text:
        if c in _SHORT_ESCAPES:
            res.append(_SHORT_ESCAPES[c])
        elif c in '"\\':
            res.append("\\" + c)
        elif c < " ":
            res.append(f"\\u{ord(c):04x}")
        else:
            res.append(c)
    res.append('"')
    return "".join(res)
