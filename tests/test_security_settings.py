from pathlib import Path

import pytest
from django.test import override_settings
from django.urls import reverse

from bearbiz.settings import _parse_csv_env


ROOT = Path(__file__).parents[1]


def test_csrf_trusted_origins_are_trimmed_and_empty_values_removed(monkeypatch) -> None:
    monkeypatch.setenv("CSRF_TRUSTED_ORIGINS", " https://one.example, ,https://two.example ")

    assert _parse_csv_env("CSRF_TRUSTED_ORIGINS") == [
        "https://one.example",
        "https://two.example",
    ]


def test_cloudflare_origin_is_configured_from_environment_without_hard_coding() -> None:
    source = (ROOT / "bearbiz/settings.py").read_text()

    assert "CSRF_TRUSTED_ORIGINS = _parse_csv_env(\"CSRF_TRUSTED_ORIGINS\")" in source
    assert "https://bearbiz.itoms.org" not in source


@pytest.mark.django_db
def test_trusted_cloudflare_origin_can_post_fiscal_settings(client) -> None:
    client = client.__class__(enforce_csrf_checks=True)
    with override_settings(CSRF_TRUSTED_ORIGINS=["https://bearbiz.itoms.org"]):
        response = client.get(reverse("settings:fiscal"))
        token = response.cookies["bearbiz_csrftoken"].value
        post = client.post(
            reverse("settings:fiscal"),
            {"fiscal_year_start_date": "2026-01-01", "csrfmiddlewaretoken": token},
            HTTP_ORIGIN="https://bearbiz.itoms.org",
            HTTP_X_FORWARDED_PROTO="https",
        )

    assert post.status_code == 302
    assert post["Location"] == reverse("settings:fiscal")
