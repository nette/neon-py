import random
import re
import time
from datetime import UTC, datetime, timedelta, timezone

import pytest

from neon import CHAIN, Date, Entity, NeonError, decode, encode
from neon.values import values_equal


def test_values_of_the_host() -> None:
    assert encode({2: "a", "x": 1, 1: "b"}) == "{2: a, x: 1, 1: b}"
    assert encode({"a": 1, "b": [1, 2]}) == "{a: 1, b: [1, 2]}"
    assert encode({}) == "{}"
    assert encode({}, True) == "{}"
    assert encode([], True) == "[]"
    assert encode(12345678901234567890) == "12345678901234567890"
    assert encode(1.0) == "1.0"
    assert encode(-0.0) == "-0.0"
    assert encode(0.1) == "0.1"
    assert (
        encode(datetime(2016, 6, 3, 19, 0, 0, 500000, tzinfo=UTC))
        == "2016-06-03 19:00:00 +0000"
    )
    assert (
        encode(Date(2016, 6, 3, 19, 0, 0, "5", "+02:00")) == "2016-06-03 19:00:00 +0200"
    )
    assert encode(Date(2016, 6, 3)) == "2016-06-03"
    assert encode(Entity("Foo", {"a": 1})) == "Foo(a: 1)"
    chain = Entity(CHAIN, [Entity("a", []), Entity("b", [1])])
    assert encode(chain) == "a()b(1)"
    assert encode({"a": {"b": 1}}, True, "  ") == "a:\n  b: 1\n\n"


def test_blocks_chosen_by_a_function() -> None:
    value = {
        "roles": ["guest", "member"],
        "mail": {"host": "smtp", "ports": [25, 587]},
        "deep": {"a": {"b": [1]}},
    }
    assert (
        encode(value, lambda _, path: not path)
        == "roles: [guest, member]\nmail: {host: smtp, ports: [25, 587]}\ndeep: {a: {b: [1]}}\n"
    )
    assert encode(value, lambda _, path: len(path) < 2) == (
        "roles:\n\t- guest\n\t- member\n\nmail:\n\thost: smtp\n\tports: [25, 587]\n\n"
        "deep:\n\ta: {b: [1]}\n\n"
    )

    def long(v: object, path: list[str]) -> bool:
        return not isinstance(v, list) or len(v) > 3

    assert encode(value, long) == (
        "roles: [guest, member]\nmail:\n\thost: smtp\n\tports: [25, 587]\n\n"
        "deep:\n\ta:\n\t\tb: [1]\n\n"
    )

    paths: list[str] = []

    def collect(v: object, path: list[str]) -> bool:
        paths.append(".".join(path))
        return True

    encode(value, collect)
    assert paths == ["", "roles", "mail", "mail.ports", "deep", "deep.a", "deep.a.b"]


def test_values_that_cannot_be_encoded() -> None:
    class Foo:
        pass

    with pytest.raises(NeonError, match=re.escape("function cannot be encoded at a.1")):
        encode({"a": [1, lambda: 1]})
    with pytest.raises(
        NeonError, match=re.escape("an instance of Foo cannot be encoded")
    ):
        encode(Foo())
    with pytest.raises(
        NeonError, match=re.escape("INF and NAN cannot be encoded to NEON")
    ):
        encode(float("inf"))
    with pytest.raises(NeonError, match=re.escape("lone surrogate")):
        encode("\ud800")
    cycle: dict[str, object] = {}
    cycle["self"] = {"cycle": cycle}
    with pytest.raises(
        NeonError, match=re.escape("cycle cannot be encoded at self.cycle")
    ):
        encode(cycle)


def test_an_entity_holding_itself_is_a_cycle() -> None:
    entity = Entity("a")
    entity.value = entity
    with pytest.raises(NeonError, match=re.escape("cycle")):
        encode(entity)


def test_values_whose_text_would_decode_as_another_value() -> None:
    attributes: list[object] = []
    attributes.append(Entity("b", attributes))  # ty: ignore[invalid-argument-type]
    with pytest.raises(NeonError, match=re.escape("cycle")):
        encode(attributes)
    shared = Entity("x")
    assert encode([shared, shared]) == "[x(), x()]"

    with pytest.raises(NeonError, match=re.escape("twice")):
        encode({1: "a", "1": "b"})
    with pytest.raises(NeonError, match=re.escape("two or more")):
        encode(Entity(CHAIN, [Entity("a")]))
    with pytest.raises(NeonError, match=re.escape("two or more")):
        encode(Entity(CHAIN, []))
    with pytest.raises(NeonError, match=re.escape("literal")):
        encode(Entity(CHAIN, [Entity("a"), Entity("1x")]))
    with pytest.raises(NeonError, match=re.escape("entity or a chain")):
        encode(Entity(Entity("a")))
    assert encode(Entity(CHAIN, [Entity("a"), Entity(5)])) == "a()5()"

    with pytest.raises(ValueError, match=re.escape("out of range")):
        Date(2024, 99, 1)
    with pytest.raises(ValueError, match=re.escape("out of range")):
        Date(2024, 1, 1, 12)
    with pytest.raises(ValueError, match=re.escape("out of range")):
        Date(2024, 1, 1, None, None, None, None, "+01:00")
    with pytest.raises(ValueError, match=re.escape("out of range")):
        Date(2024, 1, 1, 1, 2, 3, "5x")
    with pytest.raises(ValueError, match=re.escape("out of range")):
        Date(10000, 1, 1)
    with pytest.raises(ValueError, match=re.escape("out of range")):
        Date(2024, 2, 30)
    assert decode("2024-02-30") == "2024-02-30"
    assert decode(encode("2024-02-30")) == "2024-02-30"
    odd = datetime(2024, 1, 1, tzinfo=timezone(timedelta(seconds=30)))
    with pytest.raises(NeonError, match=re.escape("offset has seconds")):
        encode(odd)


def nested(n: int) -> object:
    return [nested(n - 1)] if n else "x"


def test_arrays_nest_at_most_500_levels_in_the_parser_and_in_the_encoder() -> None:
    assert decode(encode(nested(500))) == nested(500)
    with pytest.raises(NeonError, match=re.escape("nested deeper than 500")):
        encode(nested(501))
    with pytest.raises(NeonError, match=re.escape("nested deeper than 500")):
        encode(Entity("e", nested(501)))  # ty: ignore[invalid-argument-type]
    with pytest.raises(NeonError, match=re.escape("Too deep nesting")):
        decode("[" * 5000)

    start = (
        time.perf_counter()
    )  # a block on the line of a dash is not tried with both indentations
    with pytest.raises(NeonError, match=re.escape("Unexpected end")):
        decode("- " * 40 + "x\n  {")
    assert time.perf_counter() - start < 1


def test_options() -> None:
    value = {"a": {"b": 1}}
    with pytest.raises(ValueError, match=re.escape("indentation")):
        encode(value, True, "x")
    with pytest.raises(ValueError, match=re.escape("indentation")):
        encode(value, True, "")
    for block_mode in (1, "yes"):
        with pytest.raises(TypeError, match=re.escape("block_mode")):
            encode([], block_mode)  # ty: ignore[invalid-argument-type]
    asked: list[object] = []

    def ask(value: object, path: list[str]) -> bool:
        asked.append(value)
        return True

    encode("scalar", ask)
    assert asked == []


def test_special_keys_survive_the_round_trip() -> None:
    value = decode("{__proto__: 1, constructor: 2, hasOwnProperty: 3}")
    assert encode(value) == "{__proto__: 1, constructor: 2, hasOwnProperty: 3}"


STRINGS = [
    "", "a", "a b", " a", "a ", "true", "On", "-", "-.5", "+.5", ":", "a:b", "#",
    "a #b", "1", "0x1F", "2016-06-03", "'", '"', "\\", "ž", "\t", "a\nb", "  a\nb",
    "\na", "a\n", "'''\nx", "x\n'''", "a\r\nb", "\u0001", "é\u2028",
]  # fmt: skip


def generate(rnd: random.Random, depth: int) -> object:
    def many(limit: int) -> list[object]:
        return [generate(rnd, depth - 1) for _ in range(int(rnd.random() * limit))]

    match int(rnd.random() * (10 if depth > 0 else 6)):
        case 0:
            return rnd.choice([None, True, False])
        case 1:
            return int(rnd.random() * 2000) - 1000
        case 2:
            return rnd.choice([0.5, -1.25, 1e-7, 1.5e300, 0.1 + 0.2, -0.0])
        case 3:
            return rnd.choice([2**64, -(2**70)])
        case 4:
            return rnd.choice(STRINGS)
        case 5:
            return rnd.choice(
                [Date(2016, 6, 3, 19, 0, 0, None, "+02:00"), Date(2016, 6, 3)]
            )
        case 6 | 7:
            return many(4)
        case 8:
            return {
                rnd.choice(STRINGS): generate(rnd, depth - 1)
                for _ in range(int(rnd.random() * 4))
            }
        case _:
            return Entity(rnd.choice(["Foo", "a b", "@x"]), many(3))  # ty: ignore[invalid-argument-type]


def test_decode_of_encode_equals_the_value() -> None:
    for seed in range(1, 3001):
        value = generate(random.Random(seed), 3)
        for block_mode in (False, True):
            text = encode(value, block_mode, "\t" if seed % 2 else "  ")
            assert values_equal(value, decode(text)), (
                f"seed {seed}, block {block_mode}: {text}"
            )
