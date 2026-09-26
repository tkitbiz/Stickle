"""Putting an AppImage in the desktop's list of applications.

An AppImage is one file the user keeps wherever they like, and nothing
adds it to the application list the way a package would. With the user's
consent Stickle writes a .desktop file and its icon into the user's data
folder (~/.local/share), and removes both when asked.

The entry, and the one that starts Stickle at login, do not name the
AppImage itself but a launcher: a symbolic link at a fixed place that each
start of an AppImage points at itself. When the AppImage moves (or a newer
one is used from elsewhere), only the link changes; the entries stay as they
are, which matters because desktops may keep using an entry they read
before it was rewritten.
"""

import os
from collections.abc import Mapping
from pathlib import Path

from stickle.platform.autostart import APP_ID, desktop_entry

LAUNCHER_NAME = "Stickle.AppImage"


def data_home(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    return Path(env.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def launcher_path(data: Path | None = None) -> Path:
    return (data or data_home()) / APP_ID / LAUNCHER_NAME


def _leads_to(link: Path, appimage: Path) -> bool:
    try:
        return link.is_symlink() and link.readlink() == appimage
    except OSError:
        return False


def point_launcher(appimage: Path, data: Path | None = None) -> bool:
    """Make the launcher lead to this AppImage; True if it had to change."""
    link = launcher_path(data)
    if _leads_to(link, appimage):
        return False
    link.parent.mkdir(parents=True, exist_ok=True)
    # Replaced in one step, so a start at that moment finds the old or the new.
    new = link.with_name(f".{LAUNCHER_NAME}.new")
    new.unlink(missing_ok=True)
    new.symlink_to(appimage)
    new.replace(link)
    return True


def launch_path(appimage: Path, data: Path | None = None) -> Path:
    """What an entry should start: the launcher, if it leads to this AppImage."""
    link = launcher_path(data)
    return link if _leads_to(link, appimage) else appimage


def running_appimage(env: Mapping[str, str] | None = None) -> Path | None:
    """The AppImage file this Stickle runs from, if it runs from one."""
    env = os.environ if env is None else env
    value = env.get("APPIMAGE")
    return Path(value) if value else None


class AppMenuEntry:
    def __init__(self, appimage: Path, icon_png: bytes, data: Path | None = None) -> None:
        self._appimage = appimage
        self._icon_png = icon_png
        folder = data or data_home()
        self._data = folder
        self.desktop_file = folder / "applications" / f"{APP_ID}.desktop"
        self.icon_file = folder / "icons" / "hicolor" / "256x256" / "apps" / f"{APP_ID}.png"

    @property
    def added(self) -> bool:
        return self.desktop_file.exists()

    def add(self) -> None:
        self.icon_file.parent.mkdir(parents=True, exist_ok=True)
        self.icon_file.write_bytes(self._icon_png)
        self.desktop_file.parent.mkdir(parents=True, exist_ok=True)
        # Replaced in one step: a desktop watching the folder never reads half a file.
        new = self.desktop_file.with_name(f".{self.desktop_file.name}.new")
        new.write_text(self._entry(), encoding="utf-8")
        new.replace(self.desktop_file)

    def remove(self) -> None:
        self.desktop_file.unlink(missing_ok=True)
        self.icon_file.unlink(missing_ok=True)

    def refresh(self) -> bool:
        """If added, bring it up to date (from naming the AppImage, say). True if rewritten."""
        if not self.added:
            return False
        try:
            if self.desktop_file.read_text(encoding="utf-8") == self._entry():
                return False
        except OSError, UnicodeDecodeError:
            pass
        self.add()
        return True

    def _entry(self) -> str:
        extra = {"Categories": "Utility;", "Keywords": "notes;sticky;memo;"}
        # The icon by its full path: an icon theme cache may not know it yet.
        command = [str(launch_path(self._appimage, self._data))]
        return desktop_entry(command, extra, icon=str(self.icon_file))
