"""NEON parser, encoder and lossless editor."""

import sys

from .builder import Builder, Place
from .dumper import dump
from .encoder import BlockFilter, encode
from .errors import NeonError
from .facade import decode, decode_file, parse_file
from .layout import Layout
from .lexer import decode_utf8, tokenize
from .nodes import (
    ArrayItemNode,
    ArrayNode,
    BlockArrayNode,
    DocumentNode,
    EntityChainNode,
    EntityNode,
    InlineArrayNode,
    ItemIndex,
    LiteralNode,
    Node,
    PathSegment,
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
    "BlockFilter",
    "Builder",
    "Date",
    "DocumentNode",
    "Entity",
    "EntityChainNode",
    "EntityNode",
    "InlineArrayNode",
    "ItemIndex",
    "Layout",
    "LiteralNode",
    "NeonError",
    "Node",
    "PathSegment",
    "Place",
    "Position",
    "StringNode",
    "Token",
    "TokenKind",
    "Trivia",
    "TriviaKind",
    "Value",
    "ValueNode",
    "decode",
    "decode_file",
    "decode_utf8",
    "dump",
    "encode",
    "locate_all",
    "parse",
    "parse_file",
    "print_node",
    "print_text",
    "tokenize",
]
