from __future__ import annotations

from pathlib import Path

import pytest
from django.test import Client
from django.urls import reverse

from apps.core import navigation


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def read(self, limit: int) -> bytes:
        assert limit == 128
        return self.body

    def close(self) -> None:
        pass


def set_remote_version(monkeypatch: pytest.MonkeyPatch, value: bytes | Exception) -> None:
    navigation.clear_version_cache()

    def fake_urlopen(*args: object, **kwargs: object) -> FakeResponse:
        assert kwargs["timeout"] == 2
        if isinstance(value, Exception):
            raise value
        return FakeResponse(value)

    monkeypatch.setattr(navigation.url_request, "urlopen", fake_urlopen)


def test_newer_remote_version_adds_update_before_pinned_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    set_remote_version(monkeypatch, b"0.10.0\n")

    items = navigation.left_nav("dashboard")

    assert [item["label"] for item in items] == [
        "Dashboard", "Performance", "Reports", "Agent", "Update available", "Settings",
    ]
    assert items[-1]["css_class"] == "nav-bottom"
    assert items[-2]["url"] == "https://github.com/iToms-hub/bearbiz/releases/latest"


@pytest.mark.parametrize("remote", [b"0.9.0", b"0.8.9"])
def test_equal_or_older_remote_version_hides_update(
    monkeypatch: pytest.MonkeyPatch, remote: bytes,
) -> None:
    set_remote_version(monkeypatch, remote)

    assert navigation.update_notification() is None
    assert all(item["label"] != "Update available" for item in navigation.left_nav("dashboard"))


@pytest.mark.parametrize("failure", [ValueError("bad response"), TimeoutError("timed out")])
def test_malformed_or_unreachable_remote_version_fails_closed(
    monkeypatch: pytest.MonkeyPatch, failure: Exception,
) -> None:
    set_remote_version(monkeypatch, b"not-semver")
    assert navigation.update_notification() is None

    set_remote_version(monkeypatch, failure)
    assert navigation.update_notification() is None


@pytest.mark.django_db()
def test_sidebar_update_markup_is_accessible_and_collapsed_compatible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_remote_version(monkeypatch, b"1.0.0")
    client = Client()

    response = client.get(reverse("dashboard"))

    assert response.status_code == 200
    html = response.content.decode()
    assert "nav-update" in html
    assert 'title="Update available: Bearbiz 1.0.0"' in html
    assert "https://github.com/iToms-hub/bearbiz/releases/latest" in html
    assert html.index("Update available") < html.index("Settings")
    assert ".sidebar .nav-bottom" in (Path(navigation.__file__).parents[2] / "templates" / "base.html").read_text()


@pytest.mark.django_db()
def test_sidebar_branding_uses_static_logo_and_hides_it_when_collapsed() -> None:
    client = Client()

    response = client.get(reverse("dashboard"))

    assert response.status_code == 200
    html = response.content.decode()
    assert 'class="sidebar-logo"' in html
    assert 'src="/static/images/bearbiz-banner.png"' in html
    assert 'alt="Bearbiz logo"' in html

    base_template = Path(navigation.__file__).parents[2] / "templates" / "base.html"
    template = base_template.read_text()
    assert ".app-shell[data-sidebar-collapsed=\"true\"] .sidebar .sidebar-logo" in template
    assert (base_template.parents[1] / "static" / "images" / "bearbiz-banner.png").is_file()
