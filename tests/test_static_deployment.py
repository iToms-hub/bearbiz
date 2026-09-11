from pathlib import Path

import pytest
from django.core.management import call_command
from django.test import Client
from PIL import Image


def test_collected_static_asset_is_served_with_debug_disabled(settings, tmp_path) -> None:
    settings.DEBUG = False
    settings.ALLOWED_HOSTS = ["testserver"]
    settings.STATIC_ROOT = tmp_path / "staticfiles"
    call_command("collectstatic", interactive=False, verbosity=0)

    response = Client().get("/static/images/bearbiz-mark.png")

    assert response.status_code == 200
    assert response["Content-Type"] == "image/png"
    assert b"".join(response.streaming_content).startswith(b"\x89PNG")

    favicon = Client().get("/static/images/bearbiz-favicon.png")
    assert favicon.status_code == 200
    assert favicon["Content-Type"] == "image/png"
    assert b"".join(favicon.streaming_content).startswith(b"\x89PNG")


def test_static_source_contains_the_regression_asset() -> None:
    asset = Path(__file__).parents[1] / "static/images/bearbiz-mark.png"

    assert asset.is_file()


def test_favicon_source_is_a_cropped_rgba_png() -> None:
    asset = Path(__file__).parents[1] / "static/images/bearbiz-favicon.png"
    data = asset.read_bytes()

    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    assert data[25] == 6  # PNG RGBA color type.
    assert int.from_bytes(data[16:20], "big") == 128
    assert int.from_bytes(data[20:24], "big") == 128
    assert asset.stat().st_size < 100_000


@pytest.mark.django_db()
def test_favicon_template_link_and_asset_preserve_transparency() -> None:
    root = Path(__file__).parents[1]
    template = (root / "templates/base.html").read_text()
    asset = root / "static/images/bearbiz-favicon.png"

    assert "{% static 'images/bearbiz-favicon.png' %}" in template
    rendered = Client().get("/").content.decode()
    assert '<link rel="icon" type="image/png" href="/static/images/bearbiz-favicon.png">' in rendered
    assert asset.is_file()
    with Image.open(asset) as image:
        assert image.format == "PNG"
        assert image.mode == "RGBA"
        assert image.size == (128, 128)
        assert image.getchannel("A").getextrema()[0] == 0
        assert all(image.getpixel(point)[3] == 0 for point in ((0, 0), (127, 0), (0, 127), (127, 127)))
    assert asset.stat().st_size < 100_000
