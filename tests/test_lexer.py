import json
import re

import pytest
from corpus import Case, load_cases

from neon import NeonError, Position, Token, Trivia, tokenize


def print_tokens(tokens: list[Token]) -> str:
    return "".join(map(str, tokens))


def short(tokens: list[Token]) -> list[str]:
    def text(prefix: str, kind: str, value: str) -> str:
        return f"{prefix}{kind}:{json.dumps(value, ensure_ascii=False)}"

    return [
        " ".join(
            [
                *(text("<", t.kind, t.text) for t in token.leading_trivia),
                text("", token.kind, token.text),
                *(text(">", t.kind, t.text) for t in token.trailing_trivia),
            ]
        )
        for token in tokens
    ]


CASES = [
    pytest.param(c, id=f"{category}/{c.name}")
    for category in ("decode", "roundtrip", "cst")
    for c in load_cases(category)
]


@pytest.mark.parametrize("case", CASES)
def test_round_trip_of_tokens_over_the_corpus(case: Case) -> None:
    text = case.read(".neon")
    assert text is not None
    assert print_tokens(tokenize(text)) == text


def test_trivia_attach_by_the_convention() -> None:
    assert short(tokenize("a: 1 # c\n\n# d\n\tb\n")) == [
        'Literal:"a"',
        'Colon:":" >Whitespace:" "',
        'Literal:"1" >Whitespace:" " >Comment:"# c" >LineEnding:"\\n"',
        (
            '<LineEnding:"\\n" <Comment:"# d" <LineEnding:"\\n" <Whitespace:"\\t"'
            ' Literal:"b" >LineEnding:"\\n"'
        ),
        'EndOfFile:""',
    ]

    assert short(tokenize("\ufeff# x\r\na # y")) == [
        (
            '<ByteOrderMark:"\ufeff" <Comment:"# x" <LineEnding:"\\r\\n"'
            ' Literal:"a" >Whitespace:" " >Comment:"# y"'
        ),
        'EndOfFile:""',
    ]

    assert short(tokenize("")) == ['EndOfFile:""']


def test_scanner_rules() -> None:
    def kinds(s: str) -> list[str]:
        return [f"{t.kind} {t.text}" for t in tokenize(s)][:-1]

    assert kinds("a:b - c -d :e") == ["Literal a:b - c -d", "Literal :e"]
    assert kinds("- a: -") == ["Dash -", "Literal a", "Colon :", "Dash -"]
    assert kinds("'a'-b") == ["String 'a'", "Dash -", "Literal b"]
    assert kinds("a #b") == ["Literal a"]
    assert kinds("[a#b]") == ["OpenBracket [", "Literal a#b", "CloseBracket ]"]
    assert kinds("'''abc'") == ["String '''abc'"]
    assert kinds("''''") == ["String ''''"]
    assert kinds("'''\n  a\n  '''x") == ["String '''\n  a\n  '''", "Literal x"]
    assert kinds("a\rb") == ["Literal a\rb"]
    assert kinds("a:\r b") == ["Literal a", "Colon :", "Literal b"]
    assert kinds('"a\\"b" "\\\\"') == ['String "a\\"b"', 'String "\\\\"']


def test_origin_positions_in_code_points() -> None:
    tokens = tokenize("ž: 🐴\r\n  b")
    assert [t.origin for t in tokens] == [
        Position(1, 1, 0),
        Position(1, 2, 1),
        Position(1, 4, 3),
        Position(2, 3, 8),
        Position(2, 4, 9),
    ]


def test_errors_of_the_scanner() -> None:
    def error(s: str) -> tuple[str, int, int] | None:
        try:
            tokenize(s)
        except NeonError as e:
            assert e.position
            return e.message, e.position.line, e.position.column
        return None

    assert error("x: `y`") == ("Unexpected '`y`'", 1, 4)
    assert error("'abc\ndef'") == ("Unexpected ''abc<new line>def''", 1, 1)
    assert error('"a\\\nb"') == ("Unexpected '\"a\\<new line>b\"'", 1, 1)
    assert error("'''\n  abc\r\n") == (
        "Unexpected ''''<new line>  abc<new line>'",
        1,
        1,
    )
    assert error("`" + "ž" * 50) == ("Unexpected '`" + "ž" * 39 + "'", 1, 1)
    assert error("a: \ud800") == ("Invalid UTF-8 sequence.", 1, 4)


def test_token_from_text_and_set_text() -> None:
    assert Token.from_text("abc").kind == "Literal"
    assert Token.from_text(":").kind == "Colon"
    assert Token.from_text("'a'").kind == "String"
    for text in ("a b c,", " a", "#a"):
        with pytest.raises(ValueError, match=re.escape("is not one token")):
            Token.from_text(text)

    token = Token.from_text("abc")
    assert token.set_text("x y").text == "x y"
    with pytest.raises(ValueError, match=re.escape("is not one token")):
        token.set_text("'q'")


def test_canonical_form_of_trivia() -> None:
    token = Token.from_text("a")
    space = Trivia.from_text(" ")
    comment = Trivia.from_text("# c")
    eol = Trivia.from_text("\n")

    token.set_trailing_trivia([space, comment, eol])
    with pytest.raises(ValueError, match=re.escape("last")):
        token.set_trailing_trivia([eol, space])
    with pytest.raises(ValueError, match=re.escape("next to each other")):
        token.set_trailing_trivia([space, space])
    with pytest.raises(ValueError, match=re.escape("followed by a line ending")):
        token.set_leading_trivia([comment])
    with pytest.raises(ValueError, match=re.escape("byte order mark")):
        token.set_leading_trivia([eol, Trivia.from_text("\ufeff")])
    with pytest.raises(ValueError, match=re.escape("is not one trivia")):
        Trivia.from_text("\n\n")
    assert comment.get_comment_text() == "c"

    ends_with_cr = Trivia.from_text("# c\r")  # a lone CR is text of the comment
    token.set_trailing_trivia([space, ends_with_cr])
    with pytest.raises(ValueError, match=re.escape("one line ending")):
        token.set_trailing_trivia([space, ends_with_cr, eol])
    token.set_trailing_trivia([space, ends_with_cr, Trivia.from_text("\r\n")])
