"""NEON parser, encoder and lossless editor."""

import sys

from .dumper import dump
from .errors import NeonError
from .lexer import decode_utf8, tokenize
from .nodes import (
    ArrayItemNode,
    ArrayNode,
    BlockArrayNode,
    DocumentNode,
    EntityChainNode,
    EntityNode,
    InlineArrayNode,
    LiteralNode,
    Node,
    StringNode,
    ValueNode,
)
from .parser import parse
from .position import Position
from .printer import locate_all, print_node, print_text
from .scanner import TokenKind, TriviaKind
from .token import Token, Trivia
from .values import CHAIN, MAX_DEPTH, Date, Entity, Value

# arrays nest 500 levels deep, and walking such a tree takes more frames than the default
sys.setrecursionlimit(max(sys.getrecursionlimit(), MAX_DEPTH * 20))

__all__ = [
    "CHAIN",
    "ArrayItemNode",
    "ArrayNode",
    "BlockArrayNode",
    "Date",
    "DocumentNode",
    "Entity",
    "EntityChainNode",
    "EntityNode",
    "InlineArrayNode",
    "LiteralNode",
    "NeonError",
    "Node",
    "Position",
    "StringNode",
    "Token",
    "TokenKind",
    "Trivia",
    "TriviaKind",
    "Value",
    "ValueNode",
    "decode_utf8",
    "dump",
    "locate_all",
    "parse",
    "print_node",
    "print_text",
    "tokenize",
]
