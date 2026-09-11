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
        "Dashboard", "Reports", "Performance", "Missed Ops", "Payroll", "Product", "Parties",
        "Agent", "Update available", "Settings",
    ]
    assert items[-1]["css_class"] == "nav-bottom"
    assert items[-2]["url"] == "https://github.com/iToms-hub/bearbiz/releases/latest"


def test_primary_navigation_has_expected_routes_and_icon_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    set_remote_version(monkeypatch, b"0.9.0")

    items = navigation.left_nav("product")

    assert [(item["label"], item["url"], item["active"]) for item in items[:8]] == [
        ("Dashboard", "/", False),
        ("Reports", "/reports/", False),
        ("Performance", "/performance/", False),
        ("Missed Ops", "/missed-ops/", False),
        ("Payroll", "/payroll/", False),
        ("Product", "/product/", True),
        ("Parties", "/parties/", False),
        ("Agent", "/agent/", False),
    ]
    assert [item["icon_asset"] for item in items[:8]] == [
        "bearbiz-dashboard.png", "bearbiz-reports.png", "bearbiz-performance.png",
        "bearbiz-missed-ops.png", "bearbiz-payroll.png", "bearbiz-product.png",
        "bearbiz-parties.png", "bearbiz-agent.png",
    ]


@pytest.mark.django_db()
@pytest.mark.parametrize(
    ("name", "feature"),
    [("missed-ops", "Missed Ops"), ("payroll", "Payroll"), ("product", "Product"), ("parties", "Parties")],
)
def test_coming_soon_pages_are_explicit_and_active(name: str, feature: str) -> None:
    response = Client().get(reverse(name))

    assert response.status_code == 200
    html = response.content.decode()
    assert f"<h1>{feature}</h1>" in html
    assert f">{feature}</h2>" in html
    assert "Coming soon" in html
    assert "not available yet" in html
    assert f'aria-label="{feature}"' in html
    assert 'class="active"' in html
    assert f'src="/static/images/bearbiz-{name}.png"' in html


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
def test_sidebar_branding_uses_static_logos_and_preserves_collapsed_slot() -> None:
    client = Client()

    response = client.get(reverse("dashboard"))

    assert response.status_code == 200
    html = response.content.decode()
    assert 'class="sidebar-logo"' in html
    assert 'src="/static/images/bearbiz-banner.png"' in html
    assert 'class="sidebar-logo-compact"' in html
    assert 'src="/static/images/bearbiz-mark.png"' in html
    assert 'alt="Bearbiz logo"' in html
    assert 'src="/static/images/bearbiz-dashboard.png"' in html
    assert 'alt="Stitched Bearbiz house dashboard icon"' in html
    assert '>🏠</span>' not in html
    assert 'src="/static/images/bearbiz-performance.png"' in html
    assert 'src="/static/images/bearbiz-reports.png"' in html
    assert 'src="/static/images/bearbiz-parties.png"' in html
    assert 'src="/static/images/bearbiz-agent.png"' in html
    assert 'src="/static/images/bearbiz-settings.png"' in html
    assert 'src="/static/images/bearbiz-menu.png"' in html
    assert 'class="sidebar-toggle-icon"' in html
    assert 'data-sidebar-toggle>☰' not in html
    assert 'alt="Stitched performance chart icon"' in html
    assert 'alt="Stitched reports document icon"' in html
    assert 'alt="Stitched party popper icon"' in html
    assert 'alt="Stitched Bearbiz agent headset icon"' in html
    assert 'alt="Stitched settings gear icon"' in html
    base_template = Path(navigation.__file__).parents[2] / "templates" / "base.html"
    template = base_template.read_text()
    assert ".sidebar-logo-slot" in template
    assert ".app-shell[data-sidebar-collapsed=\"true\"] .sidebar .sidebar-logo" in template
    assert ".app-shell[data-sidebar-collapsed=\"true\"] .sidebar .sidebar-logo-compact" in template
    assert "height: 6.4rem;" in template
    assert "display: none;" in template.split(
        ".app-shell[data-sidebar-collapsed=\"true\"] .sidebar .sidebar-logo", 1
    )[1].split("}", 1)[0]
    static_dir = base_template.parents[1] / "static" / "images"
    assert (static_dir / "bearbiz-banner.png").is_file()
    compact_logo = static_dir / "bearbiz-mark.png"
    assert compact_logo.is_file()
    assert compact_logo.read_bytes()[25] == 6  # PNG RGBA color type.
    dashboard_logo = static_dir / "bearbiz-dashboard.png"
    assert dashboard_logo.is_file()
    assert dashboard_logo.read_bytes()[25] == 6  # PNG RGBA color type.
    assert dashboard_logo.stat().st_size < 750_000
    for asset in (
        "bearbiz-performance.png", "bearbiz-reports.png", "bearbiz-parties.png",
        "bearbiz-agent.png", "bearbiz-settings.png",
    ):
        icon = static_dir / asset
        assert icon.is_file()
        assert icon.read_bytes()[25] == 6  # PNG RGBA color type.
        assert icon.stat().st_size < 750_000
    menu_icon = static_dir / "bearbiz-menu.png"
    assert menu_icon.is_file()
    assert menu_icon.read_bytes()[25] == 6  # PNG RGBA color type.
    assert menu_icon.stat().st_size < 750_000

    assert ".sidebar-nav-icon" in template
    assert ".sidebar-toggle-icon" in template
    assert ".sidebar-dashboard-icon" in template
    toggle_css = template.split(".sidebar-toggle {", 1)[1].split("}", 1)[0]
    assert "border: 0;" in toggle_css
    assert "border-radius: 0;" in toggle_css
    assert "background: transparent;" in toggle_css
    assert "padding: 0;" in toggle_css
    assert ".sidebar-toggle:hover" in template
    assert ".sidebar-toggle:focus-visible" in template
    assert "width: 1.5rem;" in template
    assert "height: 1.5rem;" in template


@pytest.mark.django_db()
def test_sidebar_toggle_follows_agent_and_lower_items_stay_ordered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_remote_version(monkeypatch, b"1.0.0")
    client = Client()
    response = client.get(reverse("dashboard"))

    assert response.status_code == 200
    html = response.content.decode()
    assert "<strong>Bearbiz</strong>" not in html
    assert html.index('class="sidebar-primary"') < html.index('bearbiz-agent.png')
    assert html.index('bearbiz-agent.png') < html.index('data-sidebar-toggle')
    assert html.index('data-sidebar-toggle') < html.index("Update available")
    assert html.index("Update available") < html.index("Settings")

    base_template = Path(navigation.__file__).parents[2] / "templates" / "base.html"
    template = base_template.read_text()
    assert ".sidebar-lower" in template
    assert "justify-content: center" in template
    assert "gap: 0;" in template
