"""The wake word: her name is accepted at the start or end, common mishearings count, ordinary words don't."""
import pytest

from zoha.wake import WakeMatcher


@pytest.fixture(scope="module")
def m():
    return WakeMatcher(["zoha", "jarvis"])


@pytest.mark.parametrize("text, command, where", [
    ("Zoha, open Spotify", "open Spotify", "start"),
    ("hey Zoha what time is it", "what time is it", "start"),
    ("open Spotify, Zoha", "open Spotify", "end"),
    ("Hazoha what time is it", "what time is it", "start"),   # "Hey Zoha" fused by speech recognition
    ("hey Zoya open chrome", "open chrome", "start"),          # common mishearing
    ("Jarvis stop", "stop", "start"),
])
def test_wake_matches(m, text, command, where):
    r = m.match(text)
    assert r is not None, text
    assert r.command == command
    assert r.position == where


def test_wake_alone(m):
    r = m.match("Zoha.")
    assert r is not None and r.position == "only" and r.command == ""


@pytest.mark.parametrize("text", [
    "open the zone",
    "I love soha ali khan",     # a real name that sounds close must not wake her mid-sentence
    "what is the weather like",
    "turn it up",
    "",
])
def test_wake_ignores_other_speech(m, text):
    assert m.match(text) is None
