"""
Runs a seeded sample of the 10,000 stress cases through the instant parser (no AI, no side effects).

The parser doesn't have to catch everything (the AI handles the rest), but whenever it DOES act it must be
right, and it must never confirm a power action on its own.
"""
from collections import Counter

import pytest

from stress.cases import build
from stress.grading import grade, parser_route

CASES = build(3000)


def _run():
    acted = Counter()
    ok = Counter()
    unsafe = []
    chat_false_positives = 0
    chat_total = 0
    for c in CASES:
        if c["cat"] == "chat":
            chat_total += 1
        route, calls = parser_route(c)
        if route is None or route.startswith("control:"):
            continue
        if c["cat"] == "chat":
            chat_false_positives += 1
        good, reason = grade(c, calls, "")
        acted[c["cat"]] += 1
        ok[c["cat"]] += bool(good)
        if reason == "unsafe_power":
            unsafe.append(c["text"])
    return acted, ok, unsafe, chat_false_positives, chat_total


@pytest.fixture(scope="module")
def result():
    return _run()


def test_parser_handles_most_commands(result):
    acted, *_ = result
    assert sum(acted.values()) / len(CASES) > 0.55


def test_parser_is_accurate_when_it_acts(result):
    acted, ok, *_ = result
    scored = {k: v for k, v in acted.items() if k != "chat"}
    total = sum(scored.values())
    right = sum(ok[k] for k in scored)
    assert right / total > 0.98, {k: f"{ok[k]}/{acted[k]}" for k in scored if ok[k] < acted[k]}


def test_parser_never_confirms_power_by_itself(result):
    _, _, unsafe, *_ = result
    assert unsafe == []


def test_parser_rarely_acts_on_small_talk(result):
    *_, fp, total = result
    assert total == 0 or fp / total < 0.05
