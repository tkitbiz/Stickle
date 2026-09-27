"""Build the fcitx5 input method plugin for the Qt that PySide6 ships.

    uv run python scripts/build_fcitx5_qt.py build/stickle.dist

PySide6 comes with Qt's own input method plugins (ibus and compose) but not
with fcitx5's, and a desktop that asks Qt for "fcitx" alone gets no input
method at all without it: no Korean, Chinese or Japanese. The plugin uses
Qt's private interfaces, so it must be built against exactly the Qt version
it runs with. Linux only; needs cmake, a C++ compiler, extra-cmake-modules
and the xkbcommon, xcb, X11, OpenGL and Wayland development files.

The plugin (fcitx5-qt, BSD-3-Clause and LGPL-2.1-or-later) goes next to the
other input method plugins, and its licences into licenses/fcitx5-qt.
"""

import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

from build_appimage import fetch
from PySide6.QtCore import qVersion

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "build" / "fcitx5-qt"

FCITX5_QT_VERSION = "5.1.16"
FCITX5_QT_SOURCE = (
    f"https://github.com/fcitx/fcitx5-qt/archive/refs/tags/{FCITX5_QT_VERSION}.tar.gz",
    "94883b1f5501b9e8e994ce1790932750457d284dae992603cb40675c00eedea5",
)
# Downloads Qt's own development files from Qt's servers and checks their digests.
AQTINSTALL = "aqtinstall==3.3.0"
PLUGIN = "libfcitx5platforminputcontextplugin.so"


def qt_prefix(version: str) -> Path:
    """Qt's development files for this version (headers, private ones included)."""
    prefix = WORK / "qt" / version / "gcc_64"
    if not (prefix / "lib" / "cmake" / "Qt6").is_dir():
        command = ["uv", "tool", "run", "--from", AQTINSTALL, "aqt", "install-qt"]
        command += ["linux", "desktop", version, "linux_gcc_64", "--outputdir", str(WORK / "qt")]
        command += ["--archives", "qtbase", "qtwayland", "icu"]
        subprocess.run(command, check=True)
    return prefix


def source() -> Path:
    folder = WORK / f"fcitx5-qt-{FCITX5_QT_VERSION}"
    if not folder.is_dir():
        with tarfile.open(fetch(*FCITX5_QT_SOURCE)) as archive:
            archive.extractall(WORK, filter="data")
    return folder


def build(qt_version: str) -> Path:
    src, build_dir = source(), WORK / f"build-{qt_version}"
    configure = ["cmake", "-S", str(src), "-B", str(build_dir), "-DCMAKE_BUILD_TYPE=Release"]
    configure += [f"-DCMAKE_PREFIX_PATH={qt_prefix(qt_version)}"]
    # Only the plugin, for Qt 6, with the input method's D-Bus client built into it.
    configure += ["-DENABLE_QT5=Off", "-DENABLE_QT6=On", "-DBUILD_ONLY_PLUGIN=On"]
    subprocess.run(configure, check=True)
    jobs = str(os.cpu_count() or 2)
    subprocess.run(["cmake", "--build", str(build_dir), "-j", jobs], check=True)
    plugin = build_dir / "qt6" / "platforminputcontext" / PLUGIN
    drop_unused_opengl(plugin)
    return plugin


# Qt's build files link these into anything that uses Qt GUI, and the linker keeps
# them although the plugin calls nothing in them; a system without them (libOpenGL
# comes with glvnd, not everywhere) would then refuse to load the plugin.
UNUSED_LIBRARIES = ("libOpenGL.so.0", "libGLX.so.0")


def drop_unused_opengl(plugin: Path) -> None:
    undefined = subprocess.run(
        ["nm", "-D", "--undefined-only", str(plugin)], capture_output=True, text=True, check=True
    ).stdout.split()
    used = [name for name in undefined if name.startswith(("gl", "glX", "_glapi"))]
    if used:
        raise SystemExit(f"the plugin calls OpenGL after all: {', '.join(used)}")
    for library in UNUSED_LIBRARIES:
        subprocess.run(["patchelf", "--remove-needed", library, str(plugin)], check=True)
    # Qt's libraries three folders up, as for the plugins PySide6 ships; not the
    # folder the development files were in while building.
    subprocess.run(["patchelf", "--set-rpath", "$ORIGIN/../../..", str(plugin)], check=True)


def main(dist: Path) -> int:
    if not sys.platform.startswith("linux"):
        raise SystemExit("the fcitx5 plugin is built on Linux")
    WORK.mkdir(parents=True, exist_ok=True)
    plugin = build(qVersion())
    plugins = dist / "PySide6" / "qt-plugins" / "platforminputcontexts"
    if not plugins.is_dir():
        raise SystemExit(f"no input method plugins in {dist}: build the app first")
    shutil.copy2(plugin, plugins / PLUGIN)
    licenses = dist / "licenses" / "fcitx5-qt"
    shutil.rmtree(licenses, ignore_errors=True)
    shutil.copytree(source() / "LICENSES", licenses)
    print(f"fcitx5-qt {FCITX5_QT_VERSION} for Qt {qVersion()} added")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
