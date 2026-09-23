from __future__ import annotations

from .errors import NeonError
from .position import Cursor
from .scanner import Scanner, TokenKind, TriviaKind
from .token import Token, Trivia, is_well_formed


def tokenize(input: str) -> list[Token]:
    """
    Splits the input into tokens with their trivia attached. The last token is
    EndOfFile. Printing all tokens in order gives back the input.
    """
    _check_well_formed(input)

    scanner = Scanner(input)
    cursor = Cursor(input)
    tokens: list[Token] = []
    pending: list[Trivia] = []  # trivia not yet attached
    last: tuple[TokenKind, int, int, list[Trivia], list[Trivia]] | None = None

    def flush() -> None:
        if last:
            kind, start, end, leading, trailing = last
            tokens.append(
                Token._trusted(
                    kind,
                    input[start:end],
                    tuple(leading),
                    tuple(trailing),
                    cursor.at(start),
                )
            )

    while item := scanner.next():
        if isinstance(item.kind, TriviaKind):
            trivia = Trivia(item.kind, input[item.start : item.end])
            # trailing trivia of the last token run up to and including the first line ending
            trailing = last[4] if last else None
            if (
                trailing is not None
                and not pending
                and not any(t.kind == TriviaKind.LINE_ENDING for t in trailing)
            ):
                trailing.append(trivia)
            else:
                pending.append(trivia)
        else:
            flush()
            last = (item.kind, item.start, item.end, pending, [])
            pending = []

    if scanner.error_at >= 0:
        text = quote(input[scanner.error_at :])
        raise NeonError(f"Unexpected '{text}'", cursor.at(scanner.error_at))

    flush()
    tokens.append(
        Token._trusted(
            TokenKind.END_OF_FILE, "", tuple(pending), (), cursor.at(len(input))
        )
    )
    return tokens


def decode_utf8(data: bytes) -> str:
    """Decodes UTF-8; invalid bytes fail with the position of the first of them."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as e:
        prefix = data[: e.start].decode("utf-8")
        raise NeonError(
            "Invalid UTF-8 sequence.", Cursor(prefix).at(len(prefix))
        ) from None


def quote(text: str) -> str:
    """Text quoted by 'Unexpected': 40 code points, a line ending as one, shown as <new line>."""
    return text.replace("\r\n", "\n")[:40].replace("\n", "<new line>")


def _check_well_formed(input: str) -> None:
    if not is_well_formed(input):
        i = next(k for k, c in enumerate(input) if "\ud800" <= c <= "\udfff")
        raise NeonError("Invalid UTF-8 sequence.", Cursor(input).at(i))
