import subprocess
import sys
from importlib.metadata import version

import stickle


def test_version_matches_package_metadata() -> None:
    assert stickle.__version__ == version("stickle")


def test_version_option_prints_version_without_starting_the_ui() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "stickle", "--version"],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == f"Stickle {stickle.__version__}"
