"""Package a Linux build folder as an AppImage.

    uv run python scripts/build_appimage.py build/stickle.dist

Writes build/Stickle-x86_64.AppImage. The packaging tool and the AppImage
runtime are downloaded at pinned versions and checked against their
published SHA-256 digests. The runtime is the static one, which does not
need libfuse2 on the host.
"""

import hashlib
import os
import shutil
import stat
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD_DIR = ROOT / "build"
TOOLS_DIR = BUILD_DIR / "tools"
APP_ID = "co.linkro.stickle"

APPIMAGETOOL = (
    "https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage",
    "ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0",
)
RUNTIME = (
    "https://github.com/AppImage/type2-runtime/releases/download/20251108/runtime-x86_64",
    "2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d",
)

APPRUN = """#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/stickle/stickle.bin" "$@"
"""


def fetch(url: str, sha256: str) -> Path:
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    target = TOOLS_DIR / url.rsplit("/", 1)[1]
    if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest() != sha256:
        with urllib.request.urlopen(url) as response:
            data: bytes = response.read()
        digest = hashlib.sha256(data).hexdigest()
        if digest != sha256:
            raise SystemExit(f"Checksum mismatch for {url}: {digest}")
        target.write_bytes(data)
    target.chmod(target.stat().st_mode | stat.S_IXUSR)
    return target


def write_icon(path: Path) -> None:
    """Render the application icon in a separate process (needs a Qt application)."""
    code = (
        "import sys; from PySide6.QtGui import QGuiApplication; "
        "from stickle.app.tray import make_icon; "
        "app = QGuiApplication(sys.argv); "
        f"sys.exit(0 if make_icon().pixmap(256, 256).save({str(path)!r}) else 1)"
    )
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    subprocess.run([sys.executable, "-c", code], check=True, env=env)


def make_appdir(dist: Path, appdir: Path) -> None:
    if appdir.exists():
        shutil.rmtree(appdir)
    shutil.copytree(dist, appdir / "usr" / "lib" / "stickle", symlinks=True)
    apprun = appdir / "AppRun"
    apprun.write_text(APPRUN)
    apprun.chmod(0o755)
    shutil.copy2(ROOT / "packaging" / "linux" / f"{APP_ID}.desktop", appdir)
    icon = appdir / f"{APP_ID}.png"
    write_icon(icon)
    hicolor = appdir / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps"
    hicolor.mkdir(parents=True)
    shutil.copy2(icon, hicolor)


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    dist = Path(argv[0])
    appdir = BUILD_DIR / "Stickle.AppDir"
    output = BUILD_DIR / "Stickle-x86_64.AppImage"
    make_appdir(dist, appdir)

    tool = fetch(*APPIMAGETOOL)
    runtime = fetch(*RUNTIME)
    # The tool is itself an AppImage; extracting it avoids needing FUSE on build machines.
    env = {**os.environ, "APPIMAGE_EXTRACT_AND_RUN": "1", "ARCH": "x86_64"}
    subprocess.run(
        [str(tool), "--no-appstream", "--runtime-file", str(runtime), str(appdir), str(output)],
        check=True,
        env=env,
    )
    print(f"Built {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
