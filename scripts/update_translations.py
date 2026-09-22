"""Extract UI strings into i18n/*.ts and compile them into the package.

uv run python scripts/update_translations.py            # extract, then compile
uv run python scripts/update_translations.py --compile  # compile only (builds)
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "src" / "stickle"
TS_DIR = ROOT / "i18n"
QM_DIR = SOURCES / "translations"
LANGUAGES = ("ko",)


def tool(name: str) -> str:
    path = shutil.which(name, path=str(Path(sys.executable).parent)) or shutil.which(name)
    if path is None:
        raise SystemExit(f"{name} not found; run through `uv run`.")
    return path


def extract(ts_file: Path) -> None:
    sources = sorted(str(path) for path in SOURCES.rglob("*.py"))
    subprocess.run(
        [
            tool("pyside6-lupdate"),
            *sources,
            "-no-obsolete",
            "-locations",
            "none",
            "-ts",
            str(ts_file),
        ],
        check=True,
        capture_output=True,
    )


def compile_to(ts_file: Path, qm_file: Path) -> None:
    qm_file.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [tool("pyside6-lrelease"), str(ts_file), "-qm", str(qm_file)],
        check=True,
        capture_output=True,
    )


def main(argv: list[str]) -> int:
    for language in LANGUAGES:
        ts_file = TS_DIR / f"stickle_{language}.ts"
        if "--compile" not in argv:
            extract(ts_file)
        compile_to(ts_file, QM_DIR / f"stickle_{language}.qm")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
