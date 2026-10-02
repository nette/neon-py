# The tree: nodes, slots, tokens and trivia

The tree is the layer everything else stands on. It has few classes, and each is what its name
says: a document, a block array, an inline array, an item of an array, an entity, a chain of
entities, a string and a literal. Their slots hold nodes and tokens, and the tokens hold the
trivia: whitespace, line endings and comments.

**You will learn:**

- how to find an item by the path of keys, and a node by its class
- what slots an item has, and how to ask for its comments and its position
- how trivia attach to tokens, and how to look at the whole tree

```shell
uv run python examples/tree/navigate.py
uv run python examples/tree/tokens.py
```

## Finding things (navigate.py)

```
key:       user
value:     root
position:  Position(line=3, column=2, offset=40)
comment:   ['change me']
slots:     LiteralNode ':' LiteralNode
entity:    (no key) -> App\Mailer
entity:    cache -> App\Cache
strings:   ['mysql:host=localhost']
```

`find_item()` takes the same keys as the decoded value, `find()` the class of a node and walks
everything below. An item is `bullet` or `key` + `colon`, then `value`, then in an inline array
the `separator`, the comma after it. A position is computed from the current tree when you ask
for it, so it is right after an edit too; `token.origin` keeps where the token stood in the
source it was read from.

## Tokens, trivia and the dump (tokens.py)

```
Literal    "key"    leading [Comment "# header", LineEnding "\n"] trailing []
Colon      ":"      leading [] trailing [Whitespace " "]
Literal    "value"  leading [] trailing [Whitespace " ", Comment "# note", LineEnding "\n"]
EndOfFile  ""       leading [] trailing []

DocumentNode
	value: BlockArrayNode
		items:
			- ArrayItemNode
				key: LiteralNode
					token: Literal "a"
				colon: Colon ":" >[Whitespace " "]
				value: InlineArrayNode
					openBracket: OpenBracket "["
					items:
						- ArrayItemNode
							value: LiteralNode
								token: Literal "1"
							separator: Comma "," >[Whitespace " "]
						- ArrayItemNode
							value: LiteralNode
								token: Literal "2"
					closeBracket: CloseBracket "]" >[Whitespace " ", Comment "# two", LineEnding "\n"]
	endOfFile: EndOfFile ""

```

Trivia attach by one rule: the trailing trivia of a token run up to and including the first line
ending, the rest belong to the next token as leading trivia. So a comment on the line of a value
is in the trailing trivia of the value, and comment lines above an item are in the leading trivia
of its first token, which is how an item knows what describes it. `dump()` prints the tree in
the format of the conformance corpus, with the names of the specification, the same in every
implementation (`openBracket` is the slot `open_bracket`).
