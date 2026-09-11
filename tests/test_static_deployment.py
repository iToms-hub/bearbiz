from pathlib import Path

from django.core.management import call_command
from django.test import Client


def test_collected_static_asset_is_served_with_debug_disabled(settings, tmp_path) -> None:
    settings.DEBUG = False
    settings.ALLOWED_HOSTS = ["testserver"]
    settings.STATIC_ROOT = tmp_path / "staticfiles"
    call_command("collectstatic", interactive=False, verbosity=0)

    response = Client().get("/static/images/bearbiz-mark.png")

    assert response.status_code == 200
    assert response["Content-Type"] == "image/png"
    assert b"".join(response.streaming_content).startswith(b"\x89PNG")


def test_static_source_contains_the_regression_asset() -> None:
    asset = Path(__file__).parents[1] / "static/images/bearbiz-mark.png"

    assert asset.is_file()