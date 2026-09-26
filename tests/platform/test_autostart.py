"""Starting Stickle at login: one file per system, and nothing else."""

import configparser
import os
import plistlib
import sys
import time
from pathlib import Path

import pytest

from stickle.platform.autostart import (
    AUTOSTART_FLAG,
    Autostart,
    Places,
    desktop_exec,
    launch_command,
)

COMMAND = ["/opt/My Apps/Stickle-x86_64.AppImage"]


class CaseKeeping(configparser.ConfigParser):
    """Desktop entry keys are case-sensitive."""

    def optionxform(self, optionstr: str) -> str:
        return optionstr


def places(tmp_path: Path) -> Places:
    return Places(home=tmp_path / "home", config=tmp_path / "config", appdata=tmp_path / "appdata")


def test_on_linux_it_is_a_desktop_file_in_autostart(tmp_path: Path) -> None:
    autostart = Autostart(places(tmp_path), "linux", COMMAND)
    assert not autostart.enabled

    autostart.enable()

    assert autostart.path == tmp_path / "config" / "autostart" / "co.linkro.stickle.desktop"
    assert autostart.enabled
    entry = CaseKeeping(interpolation=None)
    entry.read(autostart.path, encoding="utf-8")
    section = entry["Desktop Entry"]
    assert section["Type"] == "Application"
    assert section["Exec"] == f'"/opt/My Apps/Stickle-x86_64.AppImage" {AUTOSTART_FLAG}'
    assert section["X-GNOME-Autostart-enabled"] == "true"

    autostart.disable()

    assert not autostart.enabled
    assert not autostart.path.exists()


def test_on_macos_it_is_a_launch_agent(tmp_path: Path) -> None:
    command = ["/Applications/Stickle.app/Contents/MacOS/Stickle"]
    autostart = Autostart(places(tmp_path), "darwin", command)

    autostart.enable()

    assert autostart.path.parent == tmp_path / "home" / "Library" / "LaunchAgents"
    agent = plistlib.loads(autostart.path.read_bytes())
    assert agent == {
        "Label": "co.linkro.stickle",
        "ProgramArguments": [*command, AUTOSTART_FLAG],
        "RunAtLoad": True,
    }


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_a_moved_program_is_followed_and_an_unmoved_one_left_alone(
    tmp_path: Path, platform: str
) -> None:
    Autostart(places(tmp_path), platform, ["/old/place/stickle"]).enable()
    moved = Autostart(places(tmp_path), platform, ["/new/place/stickle"])

    assert moved.refresh()
    assert b"/new/place/stickle" in moved.path.read_bytes()

    written = moved.path.stat().st_mtime_ns
    time.sleep(0.01)
    assert not moved.refresh()
    assert moved.path.stat().st_mtime_ns == written


def test_refreshing_does_not_turn_it_on(tmp_path: Path) -> None:
    autostart = Autostart(places(tmp_path), "linux", COMMAND)

    assert not autostart.refresh()
    assert not autostart.enabled


def test_nothing_is_written_outside_the_user_folders(tmp_path: Path) -> None:
    for platform in ("linux", "darwin"):
        Autostart(places(tmp_path), platform, COMMAND).enable()

    written = {path for path in tmp_path.rglob("*") if path.is_file()}
    assert all(path.is_relative_to(tmp_path) for path in written)
    assert len(written) == 2


@pytest.mark.parametrize(
    ("command", "exec_line"),
    [
        (["/usr/bin/stickle"], "/usr/bin/stickle"),
        (["/home/me/내 앱/Stickle.AppImage"], '"/home/me/내 앱/Stickle.AppImage"'),
        (["/a/b", "50%"], "/a/b 50%%"),
        (['/a/"quoted"'], '"/a/\\"quoted\\""'),
        (["/a/$HOME"], '"/a/\\$HOME"'),
    ],
)
def test_desktop_exec_quoting(command: list[str], exec_line: str) -> None:
    assert desktop_exec(command) == exec_line


def test_the_appimage_is_what_starts_stickle_when_there_is_one() -> None:
    assert launch_command({"APPIMAGE": "/tmp/Stickle.AppImage"}) == ["/tmp/Stickle.AppImage"]
    assert launch_command({}) == [sys.executable, "-m", "stickle"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows shortcuts")
def test_on_windows_it_is_a_shortcut_in_the_startup_folder(tmp_path: Path) -> None:
    if sys.platform != "win32":  # also tells the type checker this is Windows
        return
    from stickle.platform.windows.shortcut import read_shortcut

    program = Path(sys.executable)
    autostart = Autostart(places(tmp_path), "win32", [str(program), "-m", "stickle"])

    autostart.enable()

    startup = tmp_path / "appdata" / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    assert autostart.path == startup / "Startup" / "Stickle.lnk"
    shortcut = read_shortcut(autostart.path)
    assert shortcut.target == program
    assert shortcut.arguments == f"-m stickle {AUTOSTART_FLAG}"
    assert shortcut.working_directory == program.parent

    moved = Autostart(places(tmp_path), "win32", [os.fspath(program), "-m", "stickle", "-X"])
    assert moved.refresh()
    assert not moved.refresh()
