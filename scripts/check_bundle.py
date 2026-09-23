"""Check that a Windows build folder runs without installing anything else.

    uv run python scripts/check_bundle.py build/stickle.dist

Every DLL that an .exe, .dll or .pyd in the folder imports must either ship
in the folder or be part of Windows itself. Redistributable runtimes such as
the Visual C++ runtime are often present on developer machines and CI
runners, which hides a missing file, so they must always ship in the folder.
"""

import re
import sys
from collections.abc import Iterable
from pathlib import Path

import pefile

BINARY_SUFFIXES = frozenset({".exe", ".dll", ".pyd"})

# Present on every supported Windows version (API sets resolve inside the OS loader).
API_SET = re.compile(r"^(api|ext)-ms-", re.IGNORECASE)

# Runtimes that are not part of a clean Windows install and must be bundled.
REDISTRIBUTABLE = re.compile(
    r"^(vcruntime\d+(_\d+)?|msvcp\d+(_\w+)?|concrt\d+|vccorlib\d+|vcomp\d+|mfc\d+\w*|python\d+)\.dll$",
    re.IGNORECASE,
)


def is_satisfied(dll: str, bundled: set[str], system_dir: Path) -> bool:
    name = dll.lower()
    if name in bundled or API_SET.match(name):
        return True
    if REDISTRIBUTABLE.match(name):
        return False
    return (system_dir / name).exists()


def imported_dlls(binary: Path) -> Iterable[str]:
    pe = pefile.PE(str(binary), fast_load=True)
    try:
        pe.parse_data_directories(
            directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]]
        )
        # The attribute only exists when the file imports anything.
        entries: list[pefile.ImportDescData] = getattr(pe, "DIRECTORY_ENTRY_IMPORT", [])
        for entry in entries:
            yield entry.dll.decode("ascii")
    finally:
        pe.close()


def missing_dlls(dist: Path, system_dir: Path) -> dict[str, list[str]]:
    """Map each unsatisfied DLL name to the files in the folder that import it."""
    binaries = [p for p in dist.rglob("*") if p.suffix.lower() in BINARY_SUFFIXES]
    bundled = {p.name.lower() for p in binaries}
    missing: dict[str, list[str]] = {}
    for binary in binaries:
        for dll in imported_dlls(binary):
            if not is_satisfied(dll, bundled, system_dir):
                missing.setdefault(dll.lower(), []).append(str(binary.relative_to(dist)))
    return missing


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    dist = Path(argv[0])
    system_dir = Path(r"C:\Windows\System32")
    missing = missing_dlls(dist, system_dir)
    if not missing:
        print(f"OK: every imported DLL ships in {dist} or is part of Windows.")
        return 0
    print("Missing DLLs (would require installing something):", file=sys.stderr)
    for dll, users in sorted(missing.items()):
        print(f"  {dll}  <- {', '.join(sorted(users)[:3])}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
