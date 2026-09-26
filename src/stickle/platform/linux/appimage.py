"""Putting an AppImage in the desktop's list of applications.

An AppImage is one file the user keeps wherever they like, and nothing
adds it to the application list the way a package would. With the user's
consent Stickle writes a .desktop file and its icon into the user's data
folder (~/.local/share), and removes both when asked. If the AppImage
has moved since (or a newer one replaced it elsewhere), the entry is
pointed at it again when Stickle starts.
"""

import os
from collections.abc import Mapping
from pathlib import Path

from stickle.platform.autostart import APP_ID, desktop_entry


def data_home(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    return Path(env.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


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
        self.desktop_file = folder / "applications" / f"{APP_ID}.desktop"
        self.icon_file = folder / "icons" / "hicolor" / "256x256" / "apps" / f"{APP_ID}.png"

    @property
    def added(self) -> bool:
        return self.desktop_file.exists()

    def add(self) -> None:
        self.icon_file.parent.mkdir(parents=True, exist_ok=True)
        self.icon_file.write_bytes(self._icon_png)
        self.desktop_file.parent.mkdir(parents=True, exist_ok=True)
        self.desktop_file.write_text(self._entry(), encoding="utf-8")

    def remove(self) -> None:
        self.desktop_file.unlink(missing_ok=True)
        self.icon_file.unlink(missing_ok=True)

    def refresh(self) -> bool:
        """If added, point it at this AppImage (moved since). True if rewritten."""
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
        return desktop_entry([str(self._appimage)], extra, icon=str(self.icon_file))
