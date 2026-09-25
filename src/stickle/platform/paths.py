"""Where the app keeps its data on each operating system."""

import os
import sys
from collections.abc import Mapping
from pathlib import Path


def data_dir(
    env: Mapping[str, str] | None = None,
    platform: str = sys.platform,
    home: Path | None = None,
) -> Path:
    """The per-user data folder (not created here)."""
    env = os.environ if env is None else env
    home = Path.home() if home is None else home
    if platform == "win32":
        base = env.get("APPDATA")
        return (Path(base) if base else home / "AppData" / "Roaming") / "Stickle"
    if platform == "darwin":
        return home / "Library" / "Application Support" / "Stickle"
    base = env.get("XDG_DATA_HOME")
    return (Path(base) if base else home / ".local" / "share") / "stickle"


def ensure_private_dir(path: Path) -> list[str]:
    """Create the folder readable only by this user; return warnings, if any.

    Linux and macOS home folders can be readable by other local users, so the
    folder is set to 700. On Windows the per-user profile already grants access
    only to the user, SYSTEM and administrators, and the folder inherits that;
    rewriting it would fight backup and roaming tools, so it is only checked.
    """
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        from stickle.platform.windows.permissions import other_readers

        readers = other_readers(path)
        return [f"other accounts can read the data folder: {', '.join(readers)}"] if readers else []
    path.chmod(0o700)
    return []
