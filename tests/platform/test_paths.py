import stat
import subprocess
import sys
from pathlib import Path

import pytest

from stickle.platform.paths import data_dir, ensure_private_dir

HOME = Path("/home/user")


def test_windows_uses_roaming_app_data() -> None:
    folder = data_dir({"APPDATA": r"C:\Users\u\AppData\Roaming"}, "win32", HOME)
    assert folder == Path(r"C:\Users\u\AppData\Roaming") / "Stickle"


def test_windows_without_app_data_falls_back_to_the_profile() -> None:
    assert data_dir({}, "win32", HOME) == HOME / "AppData" / "Roaming" / "Stickle"


def test_macos_uses_application_support() -> None:
    assert data_dir({}, "darwin", HOME) == HOME / "Library" / "Application Support" / "Stickle"


def test_linux_follows_xdg_data_home() -> None:
    assert data_dir({"XDG_DATA_HOME": "/data"}, "linux", HOME) == Path("/data/stickle")
    assert data_dir({"XDG_DATA_HOME": ""}, "linux", HOME) == HOME / ".local/share/stickle"
    assert data_dir({}, "linux", HOME) == HOME / ".local/share/stickle"


def test_an_explicit_data_folder_wins_everywhere() -> None:
    for platform in ("win32", "darwin", "linux"):
        assert data_dir({"STICKLE_DATA_DIR": "/tmp/x", "APPDATA": "C:/a"}, platform, HOME) == Path(
            "/tmp/x"
        )


def test_private_dir_is_created_with_parents(tmp_path: Path) -> None:
    folder = tmp_path / "a" / "b"
    ensure_private_dir(folder)
    assert folder.is_dir()
    ensure_private_dir(folder)  # again: no error


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_private_dir_is_readable_only_by_the_user(tmp_path: Path) -> None:
    folder = tmp_path / "data"
    folder.mkdir(mode=0o755)
    assert ensure_private_dir(folder) == []
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700


@pytest.mark.skipif(sys.platform != "win32", reason="Windows access lists")
def test_windows_profile_folder_raises_no_warning(tmp_path: Path) -> None:
    assert ensure_private_dir(tmp_path / "data") == []


@pytest.mark.skipif(sys.platform != "win32", reason="Windows access lists")
def test_windows_warns_when_everyone_can_read(tmp_path: Path) -> None:
    folder = tmp_path / "data"
    folder.mkdir()
    # S-1-1-0 is Everyone; the SID form works in every Windows language.
    subprocess.run(
        ["icacls", str(folder), "/grant", "*S-1-1-0:(R)"], check=True, capture_output=True
    )

    warnings = ensure_private_dir(folder)
    assert len(warnings) == 1
    assert "S-1-1-0" in warnings[0]
