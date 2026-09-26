"""Starting Stickle when the user logs in, with one file and nothing else.

Windows: a shortcut in the user's Startup folder. Linux: a .desktop file in
~/.config/autostart. macOS: a LaunchAgent property list. No registry and no
settings stores: whether Stickle starts at login is whether that file is
there, so turning it off in the system's own settings shows here too, and
removing the file leaves nothing behind.

Started this way, Stickle gets --autostart, so it stays out of the way
(no Stickle window at start).
"""

import os
import plistlib
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

APP_ID = "co.linkro.stickle"
AUTOSTART_FLAG = "--autostart"


def launch_command(env: Mapping[str, str] | None = None) -> list[str]:
    """What starts this Stickle: the AppImage, the built program, or Python."""
    env = os.environ if env is None else env
    if appimage := env.get("APPIMAGE"):
        return [appimage]
    if "__compiled__" in globals():  # a Nuitka build: sys.executable is the program
        return [sys.executable]
    return [sys.executable, "-m", "stickle"]


def desktop_exec(command: list[str]) -> str:
    """A command line as a .desktop Exec value (quoting and % as the spec asks)."""

    def quote(argument: str) -> str:
        argument = argument.replace("%", "%%")
        if not any(c in argument for c in " \t\n\"'\\><~|&;$*?#()`"):
            return argument
        escaped = "".join("\\" + c if c in '"`$\\' else c for c in argument)
        return f'"{escaped}"'

    return " ".join(quote(argument) for argument in command)


def desktop_entry(command: list[str], extra: dict[str, str] | None = None) -> str:
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        "Name=Stickle",
        "Comment=Sticky notes that follow you",
        f"Exec={desktop_exec(command)}",
        f"Icon={APP_ID}",
        "Terminal=false",
        f"StartupWMClass={APP_ID}",
    ]
    lines += [f"{key}={value}" for key, value in (extra or {}).items()]
    return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class Places:
    """Where the per-user files go; replaceable for tests."""

    home: Path
    config: Path  # XDG_CONFIG_HOME on Linux
    appdata: Path  # %APPDATA% on Windows

    @classmethod
    def of_this_user(cls, env: Mapping[str, str] | None = None) -> Places:
        env = os.environ if env is None else env
        home = Path.home()
        config = Path(env.get("XDG_CONFIG_HOME") or home / ".config")
        appdata = Path(env.get("APPDATA") or home / "AppData" / "Roaming")
        return cls(home, config, appdata)


class Autostart:
    def __init__(
        self,
        places: Places | None = None,
        platform: str = sys.platform,
        command: list[str] | None = None,
    ) -> None:
        self._places = places or Places.of_this_user()
        self._platform = platform
        self._command = [*(command or launch_command()), AUTOSTART_FLAG]

    @property
    def path(self) -> Path:
        if self._platform == "win32":
            startup = self._places.appdata / "Microsoft" / "Windows" / "Start Menu"
            return startup / "Programs" / "Startup" / "Stickle.lnk"
        if self._platform == "darwin":
            return self._places.home / "Library" / "LaunchAgents" / f"{APP_ID}.plist"
        return self._places.config / "autostart" / f"{APP_ID}.desktop"

    @property
    def enabled(self) -> bool:
        return self.path.exists()

    def enable(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self._platform == "win32":
            self._write_shortcut()
        else:
            self.path.write_bytes(self._content())

    def disable(self) -> None:
        self.path.unlink(missing_ok=True)

    def refresh(self) -> bool:
        """If on, point it at this Stickle (moved or updated since). True if rewritten."""
        if not self.enabled or self._is_current():
            return False
        self.enable()
        return True

    def _content(self) -> bytes:
        if self._platform == "darwin":
            agent = {"Label": APP_ID, "ProgramArguments": self._command, "RunAtLoad": True}
            return plistlib.dumps(agent)
        extra = {"X-GNOME-Autostart-enabled": "true"}
        return desktop_entry(self._command, extra).encode("utf-8")

    def _is_current(self) -> bool:
        if self._platform != "win32":
            try:
                return self.path.read_bytes() == self._content()
            except OSError:
                return False
        if sys.platform == "win32":
            from stickle.platform.windows.shortcut import read_shortcut

            try:
                shortcut = read_shortcut(self.path)
            except OSError:
                return False
            target, *arguments = self._command
            return Path(shortcut.target) == Path(target) and shortcut.arguments == _join(arguments)
        return False

    def _write_shortcut(self) -> None:
        if sys.platform != "win32":
            raise OSError("Windows shortcuts can only be written on Windows")
        from stickle.platform.windows.shortcut import Shortcut, write_shortcut

        target, *arguments = self._command
        write_shortcut(
            self.path,
            Shortcut(Path(target), _join(arguments), Path(target).parent, "Stickle"),
        )


def _join(arguments: list[str]) -> str:
    """Arguments as one Windows command line string."""
    return subprocess.list2cmdline(arguments)
