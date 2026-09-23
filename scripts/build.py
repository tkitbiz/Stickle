"""Build a standalone Stickle folder with Nuitka.

    uv run python scripts/build.py

The result is build/stickle.dist/ (on Linux also build/Stickle-x86_64.AppImage).
The folder is deliberately plain: no self-extracting single file and no
executable packing, both of which make antivirus products suspicious of
Python applications.
"""

import subprocess
import sys
from pathlib import Path

from stickle import __version__

ROOT = Path(__file__).resolve().parents[1]
BUILD_DIR = ROOT / "build"
DIST_DIR = BUILD_DIR / "stickle.dist"


def nuitka_command() -> list[str]:
    command = [
        sys.executable,
        "-m",
        "nuitka",
        "--mode=standalone",
        "--enable-plugin=pyside6",
        # Needs Qt6Pdf, which is not shipped; notes never show PDFs.
        "--noinclude-dlls=PySide6/qt-plugins/imageformats/qpdf*",
        "--include-package-data=stickle",
        f"--output-dir={BUILD_DIR}",
        "--assume-yes-for-downloads",
        "--remove-output",
        "--product-name=Stickle",
        f"--product-version={__version__}",
        f"--file-version={__version__}",
        "--file-description=Stickle",
        "--copyright=Stickle contributors, GPL-3.0-or-later",
    ]
    if sys.platform == "win32":
        command += [
            "--msvc=latest",
            # Ship the Visual C++ runtime so nothing has to be installed.
            "--include-windows-runtime-dlls=yes",
            # No console window when started from Explorer, but --version still
            # prints when started from a terminal.
            "--windows-console-mode=attach",
            "--output-filename=stickle",
        ]
    elif sys.platform == "linux":
        command += [
            # Input method plugins (ibus, compose) are not in Nuitka's default set,
            # and without them there is no Korean, Chinese or Japanese input.
            "--include-qt-plugins=sensible,platforminputcontexts",
            # Plugins for things notes never use, whose dependencies are not shipped:
            # printing (CUPS), embedded displays (EGLFS), the GTK 3 theme bridge,
            # the virtual keyboard (Qt Quick) and PDF images.
            "--noinclude-qt-plugins=printsupport,egldeviceintegrations",
            "--noinclude-dlls=PySide6/qt-plugins/platformthemes/libqgtk3*",
            "--noinclude-dlls=PySide6/qt-plugins/platforms/libqeglfs*",
            "--noinclude-dlls=PySide6/qt-plugins/platforms/libqminimalegl*",
            "--noinclude-dlls=PySide6/qt-plugins/platforminputcontexts/libqtvirtualkeyboard*",
            "--noinclude-dlls=PySide6/qt-plugins/imageformats/libqpdf*",
            "--noinclude-dlls=libQt6EglFs*",
            "--noinclude-dlls=libQt6Quick*",
            "--noinclude-dlls=libQt6Qml*",
            # The executable keeps Nuitka's default name, stickle.bin: a plain
            # "stickle" would collide with the stickle/ data folder next to it.
        ]
    command.append(str(ROOT / "src" / "stickle"))
    return command


def main() -> int:
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "update_translations.py"), "--compile"], check=True
    )
    subprocess.run(nuitka_command(), check=True, cwd=ROOT)
    print(f"Built {DIST_DIR}")
    if sys.platform == "linux":
        for script in ("bundle_linux_libs.py", "build_appimage.py"):
            script_path = ROOT / "scripts" / script
            subprocess.run([sys.executable, str(script_path), str(DIST_DIR)], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
