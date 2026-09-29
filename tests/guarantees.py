"""The guarantees of editing that hold for any tree."""

from collections.abc import Callable

from neon import DocumentNode, Node, Token, TokenKind, TriviaKind, dump, parse


def check_tree(document: DocumentNode) -> None:
    """Parents agree with a walk, nothing stands twice, trivia are canonical, it reparses."""
    seen: set[int] = set()

    def walk(node: Node) -> None:
        for child in node.get_children():
            assert child.parent is node, "parents agree with the walk"
            assert id(child) not in seen, "no node or token stands twice"
            seen.add(id(child))
            if isinstance(child, Node):
                walk(child)

    walk(document)
    check_canonical(document)
    assert dump(parse(document.print())) == dump(document), "the printed tree reparses"


def check_canonical(document: DocumentNode) -> None:
    """The trivia of the document are canonical, checked by the rules, not by a reparse."""
    tokens = document.get_tokens()
    for i, token in enumerate(tokens):
        trailing = token.trailing_trivia
        endings = [t for t in trailing if t.kind == TriviaKind.LINE_ENDING]
        assert len(endings) <= 1, "one line ending in the trailing trivia"
        assert not endings or trailing[-1].kind == TriviaKind.LINE_ENDING, (
            "and the last"
        )
        if i and not any(
            t.kind == TriviaKind.LINE_ENDING for t in tokens[i - 1].trailing_trivia
        ):
            assert not token.leading_trivia, (
                "no leading trivia on the line of the one before"
            )
        for trivia in (token.leading_trivia, token.trailing_trivia):
            assert len({id(t) for t in trivia}) == len(trivia), (
                "an instance stands once"
            )
            for k, t in enumerate(trivia):
                following = trivia[k + 1] if k + 1 < len(trivia) else None
                assert not (
                    t.kind == TriviaKind.WHITESPACE
                    and following
                    and following.kind == TriviaKind.WHITESPACE
                ), "no two whitespace trivia side by side"
                assert not (
                    t.text.endswith("\r")
                    and following
                    and following.text.startswith("\n")
                ), "no carriage return before a line feed"
                if t.kind == TriviaKind.BYTE_ORDER_MARK:
                    assert i == 0 and trivia is token.leading_trivia and k == 0, (
                        "BOM at start"
                    )
                elif t.kind == TriviaKind.COMMENT and (
                    following is None or following.kind != TriviaKind.LINE_ENDING
                ):
                    at_end = token.kind == TokenKind.END_OF_FILE or (
                        i + 1 < len(tokens)
                        and tokens[i + 1].kind == TokenKind.END_OF_FILE
                    )
                    assert at_end, (
                        "a comment ends its line, but at the end of the input"
                    )
    assert document.end_of_file.trailing_trivia == ()


def snapshot(*nodes: Node) -> Callable[[], None]:
    """The state of everything reachable from the nodes; the result checks it is the same."""

    def tokens() -> list[Token]:
        return [token for node in nodes for token in node.get_tokens()]

    def capture(node: Node) -> list[object]:
        return [node.parent, *node.get_children(), getattr(node, "nullable", None)]

    before = tokens()
    states = [
        (t, t.parent, t.text, t.leading_trivia, t.trailing_trivia) for t in before
    ]
    node_states: list[tuple[Node, list[object]]] = []

    def walk(node: Node) -> None:
        node_states.append((node, capture(node)))
        for child in node.get_children():
            if isinstance(child, Node):
                walk(child)

    for node in nodes:
        walk(node)
    texts = [node.print() for node in nodes]

    def check() -> None:
        assert [node.print() for node in nodes] == texts, (
            "a refused operation keeps the text"
        )
        now = tokens()
        assert len(now) == len(before), "and the tokens"
        assert all(a is b for a, b in zip(now, before, strict=True)), "and the tokens"
        for token, parent, text, leading, trailing in states:
            assert token.parent is parent and token.text == text, "and every token"
            assert token.leading_trivia is leading, "and every token"
            assert token.trailing_trivia is trailing, "and every token"
        for node, captured in node_states:
            current = capture(node)
            assert len(current) == len(captured), "and every node"
            assert all(a is b for a, b in zip(current, captured, strict=True)), (
                "and every node with its parent, children and flags"
            )

    return check
