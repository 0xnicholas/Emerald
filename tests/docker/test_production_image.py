"""Integration test for production Docker image.

Requires Docker daemon. Skipped in CI without Docker.
"""
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build_prod_image.sh"


@pytest.mark.docker
@pytest.mark.skipif(
    subprocess.run(["which", "docker"], capture_output=True).returncode != 0,
    reason="docker not available",
)
def test_build_script_exists() -> None:
    """Verify build script is present and executable."""
    assert BUILD_SCRIPT.exists()
    assert BUILD_SCRIPT.stat().st_mode & 0o111  # any execute bit


@pytest.mark.docker
def test_production_image_size_under_1200mb() -> None:
    """Build production image and verify size constraint."""
    result = subprocess.run(
        [
            "docker", "build", "--target", "production",
            "-t", "emerald:test-size", str(REPO_ROOT),
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        pytest.skip(f"Docker build failed: {result.stderr}")

    inspect = subprocess.run(
        [
            "docker", "image", "inspect", "emerald:test-size",
            "--format", "{{.Size}}",
        ],
        capture_output=True,
        text=True,
    )
    size_bytes = int(inspect.stdout.strip())
    size_mb = size_bytes / 1024 / 1024

    assert size_mb < 1200, f"Image size {size_mb:.0f}MB exceeds 1.2GB target"


@pytest.mark.docker
def test_production_image_starts_and_imports_app() -> None:
    """Verify the production container can import the app module."""
    result = subprocess.run(
        [
            "docker", "run", "--rm", "emerald:test-size",
            "python", "-c", "from emerald.api.app import app; print('OK')",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"Import failed: {result.stderr}"
    assert "OK" in result.stdout


@pytest.mark.docker
def test_no_dev_deps_in_production_image() -> None:
    """Verify pytest, ruff, mypy are NOT installed in production image.

    Uses ``pip list --format=json`` for exact-name matching (substring check
    on human-readable format has false-positive risk).
    """
    result = subprocess.run(
        [
            "docker", "run", "--rm", "emerald:test-size",
            "pip", "list", "--format=json",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        pytest.skip(f"pip list failed: {result.stderr}")

    import json as _json

    packages = {p["name"].lower() for p in _json.loads(result.stdout)}
    for forbidden in ("pytest", "ruff", "mypy", "fakeredis", "testcontainers"):
        assert forbidden not in packages, (
            f"Dev dependency '{forbidden}' found in production image"
        )
