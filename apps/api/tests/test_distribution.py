from __future__ import annotations

import tomllib
from pathlib import Path


def test_mit_license_is_packaged_and_copied_into_runtime_images() -> None:
    api_root = Path(__file__).resolve().parents[1]
    repository_root = api_root.parents[1]
    api_license = (api_root / "LICENSE").read_text(encoding="utf-8")
    root_license = (repository_root / "LICENSE").read_text(encoding="utf-8")

    assert api_license == root_license
    assert api_license.startswith("MIT License\n")
    with (api_root / "pyproject.toml").open("rb") as project_file:
        project = tomllib.load(project_file)
    assert project["project"]["license-files"] == ["LICENSE"]
    api_dockerfile = (api_root / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY pyproject.toml uv.lock LICENSE ./" in api_dockerfile
    assert "COPY LICENSE /licenses/LICENSE" in api_dockerfile
    assert "COPY LICENSE /licenses/LICENSE" in (
        repository_root / "apps" / "web" / "Dockerfile"
    ).read_text(encoding="utf-8")
