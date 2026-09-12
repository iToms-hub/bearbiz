from pathlib import Path
import tomllib

import bearbiz


ROOT = Path(__file__).parents[1]
RELEASE = "0.9.8.1"


def test_release_metadata_is_consistent() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert (ROOT / "VERSION").read_text().strip() == RELEASE
    assert bearbiz.__version__ == RELEASE
    assert pyproject["project"]["version"] == RELEASE


def test_release_references_use_current_image_and_ai_user_agent() -> None:
    compose = (ROOT / "compose.portainer.yml").read_text()
    readme = (ROOT / "README.md").read_text()
    deployment_docs = (ROOT / "docs/portainer-deployment.md").read_text()
    ai = (ROOT / "apps/core/ai.py").read_text()

    assert f"BEARBIZ_IMAGE_TAG:-{RELEASE}" in compose
    assert f"ghcr.io/itoms-hub/bearbiz:{RELEASE}" in readme
    assert f"ghcr.io/itoms-hub/bearbiz:{RELEASE}" in deployment_docs
    assert ai.count(f"bearbiz-ai/{RELEASE}") == 2
