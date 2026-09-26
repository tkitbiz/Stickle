"""An AppImage in the desktop's application list."""

import configparser
from pathlib import Path

from stickle.platform.autostart import desktop_exec
from stickle.platform.linux.appimage import AppMenuEntry, data_home, running_appimage

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


def test_refreshing_does_not_add_it(tmp_path: Path) -> None:
    entry = AppMenuEntry(tmp_path / "Stickle.AppImage", ICON, tmp_path / "share")

    assert not entry.refresh()
    assert not entry.added


def test_where_things_are() -> None:
    assert running_appimage({"APPIMAGE": "/opt/Stickle.AppImage"}) == Path("/opt/Stickle.AppImage")
    assert running_appimage({}) is None
    assert data_home({"XDG_DATA_HOME": "/data"}) == Path("/data")
