"""Instant command parsing (runs before the AI): control phrases, music, volume, timers, compound commands."""
import pytest

from zoha import intents
from zoha.nlu import Ctx, parse


@pytest.mark.parametrize("text, expected", [
    ("stop", "stop"),
    ("never mind", "stop"),
    ("go to sleep", "sleep"),
    ("be quiet until I call you", "sleep"),
    ("bye zoha", "sleep"),
])
def test_control_phrases(text, expected):
    assert intents.control(text) == expected


@pytest.mark.parametrize("text", ["pause", "shut down the pc", "what time is it"])
def test_control_ignores_normal_commands(text):
    assert intents.control(text) is None


def test_play_goes_to_youtube():
    assert intents.fast_route("play perfect by ed sheeran") == ("play_youtube", {"query": "perfect by ed sheeran", "where": "default"})


def test_volume_level():
    assert intents.fast_route("set volume to 40") == ("set_volume", {"level": 40})


def test_time_question():
    assert intents.fast_route("what time is it") == ("get_datetime", {})


def test_chat_is_not_a_command():
    assert intents.offline_route("how are you") is None


def test_compound_command_parses_in_order():
    acts = parse("open chrome and set volume to 30", Ctx())
    assert [(a.tool, a.args) for a in acts] == [("open_app", {"name": "chrome"}), ("set_volume", {"level": 30})]


def test_timer_minutes():
    acts = parse("set a timer for 5 minutes", Ctx())
    assert len(acts) == 1 and acts[0].tool == "set_timer" and acts[0].args["minutes"] == 5
