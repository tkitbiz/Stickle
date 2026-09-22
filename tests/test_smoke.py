import subprocess
import sys
from importlib.metadata import version

import stickle


def test_version_matches_package_metadata() -> None:
    assert stickle.__version__ == version("stickle")


def test_module_entry_point_prints_version_and_exits_cleanly() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "stickle"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0
    assert result.stdout.strip() == f"Stickle {stickle.__version__}"
