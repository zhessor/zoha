"""Finding files from how people SAY names: 'gym underscore website dot html', 'jim' for 'gym', any word order."""
import time

import pytest

from zoha import tools as T


@pytest.mark.parametrize("spoken, written", [
    ("gym underscore website dot html", "gym_website.html"),
    ("report bracket two dot pdf", "report (2).pdf"),
])
def test_spoken_names(spoken, written):
    assert T.spoken_name(spoken) == written


def test_sound_alike_keys():
    assert T._sound("jim") == T._sound("gym")
    assert T._sound("kafe") == T._sound("cafe")


@pytest.fixture
def home(tmp_path, monkeypatch):
    (tmp_path / "Desktop").mkdir()
    (tmp_path / "Documents").mkdir()
    monkeypatch.setattr(T.Path, "home", classmethod(lambda cls: tmp_path))
    return tmp_path


def test_find_exact_name(home):
    f = home / "Desktop" / "gym_powai.html"
    f.write_text("x")
    assert T.find_named("gym_powai.html") == f


def test_find_misheard_and_reordered(home):
    f = home / "Desktop" / "gym_powai.html"
    f.write_text("x")
    assert T.find_named("jim powai website") == f or T.find_named("powai jim") == f


def test_find_prefers_newest(home):
    old = home / "Desktop" / "gym_site.html"
    new = home / "Desktop" / "gym_site (2).html"
    old.write_text("old")
    time.sleep(0.02)
    new.write_text("new")
    assert T.find_named("gym site") == new


def test_nothing_found_returns_none(home):
    assert T.find_named("quarterly budget") is None
