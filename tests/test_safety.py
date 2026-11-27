"""Nothing risky happens without an explicit yes."""
import subprocess

import pytest

from zoha import site_plugin as S
from zoha import tools as T


@pytest.mark.parametrize("text", ["yes", "yes go ahead", "yep", "do it", "go ahead"])
def test_clear_yes_confirms(text):
    assert S.is_confirm(text)


@pytest.mark.parametrize("text", ["no", "cancel", "hmm", "yes but change the price", "what was that again", ""])
def test_anything_else_does_not_confirm(text):
    assert not S.is_confirm(text)


def test_power_asks_first_and_never_acts_on_a_claimed_confirmation(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("a system command ran without a confirmed yes")

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(T.os, "system", boom)
    T.CTX.last_user_text = "yes"            # even if the last message sounds like yes...
    for action in ("shutdown", "restart", "sleep"):
        out = T.REGISTRY["power"].fn(action=action, confirmed=True)   # ...and the model claims confirmation
        assert out.startswith("NOT DONE YET")
        T._POWER_PENDING.clear()


def test_site_plugin_has_no_apply_tool_for_the_model():
    """The model can only PROPOSE site changes. Applying is done by the engine after the user's yes."""
    site_tools = [n for n in T.REGISTRY if n.startswith("site_")]
    assert not any("apply" in n for n in site_tools)
    assert "site_propose" in site_tools   # importing the plugin registers its tools
