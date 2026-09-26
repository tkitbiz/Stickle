"""An AppImage in the desktop's application list."""

import configparser
import sys
from pathlib import Path

import pytest

from stickle.platform.autostart import desktop_exec, launch_command
from stickle.platform.linux.appimage import (
    AppMenuEntry,
    data_home,
    launch_path,
    launcher_path,
    point_launcher,
    running_appimage,
)

ICON = b"\x89PNG fake icon"


class CaseKeeping(configparser.ConfigParser):
    def optionxform(self, optionstr: str) -> str:
        return optionstr


def entry_values(entry: AppMenuEntry) -> dict[str, str]:
    parser = CaseKeeping(interpolation=None)
    parser.read(entry.desktop_file, encoding="utf-8")
    return dict(parser["Desktop Entry"])


def test_adding_writes_a_desktop_file_and_its_icon(tmp_path: Path) -> None:
    appimage = tmp_path / "내 앱" / "Stickle-x86_64.AppImage"
    entry = AppMenuEntry(appimage, ICON, tmp_path / "share")
    assert not entry.added

    entry.add()

    assert entry.added
    assert entry.desktop_file == tmp_path / "share" / "applications" / "co.linkro.stickle.desktop"
    assert entry.icon_file.read_bytes() == ICON
    values = entry_values(entry)
    assert values["Exec"] == desktop_exec([str(appimage)])
    assert values["Exec"].startswith('"')  # the space in the folder name is quoted
    assert values["Icon"] == str(entry.icon_file)
    assert values["Categories"] == "Utility;"
    assert values["StartupWMClass"] == "co.linkro.stickle"


def test_removing_leaves_nothing_behind(tmp_path: Path) -> None:
    entry = AppMenuEntry(tmp_path / "Stickle.AppImage", ICON, tmp_path / "share")
    entry.add()

    entry.remove()

    assert not entry.added
    assert not entry.icon_file.exists()


def test_a_moved_appimage_is_followed(tmp_path: Path) -> None:
    AppMenuEntry(tmp_path / "old" / "Stickle.AppImage", ICON, tmp_path / "share").add()
    moved = AppMenuEntry(tmp_path / "new" / "Stickle.AppImage", ICON, tmp_path / "share")

    assert moved.refresh()
    assert entry_values(moved)["Exec"] == desktop_exec([str(tmp_path / "new" / "Stickle.AppImage")])
    assert not moved.refresh()


symlinks = pytest.mark.skipif(sys.platform == "win32", reason="AppImages: Linux symbolic links")


@symlinks
def test_entries_start_the_launcher_which_follows_the_appimage(tmp_path: Path) -> None:
    share = tmp_path / "share"
    old = tmp_path / "old" / "Stickle.AppImage"
    assert point_launcher(old, share)
    entry = AppMenuEntry(old, ICON, share)
    entry.add()
    launcher = launcher_path(share)
    assert launcher == share / "co.linkro.stickle" / "Stickle.AppImage"
    assert entry_values(entry)["Exec"] == desktop_exec([str(launcher)])
    assert launch_command({"APPIMAGE": str(old), "XDG_DATA_HOME": str(share)}) == [str(launcher)]

    # Moved: the next start points the launcher; the entry is left as it was.
    new = tmp_path / "new" / "Stickle.AppImage"
    written = entry.desktop_file.read_bytes()
    assert point_launcher(new, share)
    assert AppMenuEntry(new, ICON, share).refresh() is False
    assert entry.desktop_file.read_bytes() == written
    assert launcher.readlink() == new
    assert not point_launcher(new, share)  # nothing to change


@symlinks
def test_an_entry_naming_the_appimage_itself_is_brought_to_the_launcher(tmp_path: Path) -> None:
    share = tmp_path / "share"
    appimage = tmp_path / "Stickle.AppImage"
    entry = AppMenuEntry(appimage, ICON, share)
    entry.add()  # no launcher yet: the AppImage itself, as before
    assert entry_values(entry)["Exec"] == desktop_exec([str(appimage)])

    point_launcher(appimage, share)

    assert entry.refresh()
    assert entry_values(entry)["Exec"] == desktop_exec([str(launcher_path(share))])
    assert not list(entry.desktop_file.parent.glob(".*.new"))  # no half-written leftovers


def test_without_a_launcher_the_appimage_itself_is_named(tmp_path: Path) -> None:
    appimage = tmp_path / "Stickle.AppImage"

    assert launch_path(appimage, tmp_path / "share") == appimage


def test_refreshing_does_not_add_it(tmp_path: Path) -> None:
    entry = AppMenuEntry(tmp_path / "Stickle.AppImage", ICON, tmp_path / "share")

    assert not entry.refresh()
    assert not entry.added


def test_where_things_are() -> None:
    assert running_appimage({"APPIMAGE": "/opt/Stickle.AppImage"}) == Path("/opt/Stickle.AppImage")
    assert running_appimage({}) is None
    assert data_home({"XDG_DATA_HOME": "/data"}) == Path("/data")
