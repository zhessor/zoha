"""Which tools the AI is offered for a request. Building a site for a business is FILE work, never the CMS plugin."""
import pytest

from zoha import brain as B
from zoha import site_plugin  # noqa: F401  (registers the site_* tools)


def test_building_a_site_offers_file_tools_and_no_cms_tools():
    names = B.select_tools("make a website of a gym in andheri east", [], set())
    assert {"write_file", "improve_file"} <= names
    assert not any(n.startswith("site_") for n in names)


def test_improving_the_page_just_made_stays_file_work():
    names = B.select_tools("the design looks basic, improve it", [], set())
    assert "improve_file" in names
    assert not any(n.startswith("site_") for n in names)


def test_site_tools_appear_when_the_user_talks_about_their_site_admin():
    names = B.select_tools("show me the enquiries on the admin", [], set())
    assert {"site_enquiries", "site_read"} <= names


def test_plain_chat_offers_no_site_tools():
    names = B.select_tools("tell me a joke", [], set())
    assert not any(n.startswith("site_") for n in names)
