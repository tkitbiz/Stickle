"""Copy the shared libraries a Linux build needs into the build folder.

    uv run python scripts/bundle_linux_libs.py build/stickle.dist

Nuitka leaves system libraries out of the folder, but many of them (for
example libxcb-cursor, required by Qt 6) are missing from default desktop
installs. Everything the folder needs is copied in, except the libraries in
packaging/linux/excludelist, which every desktop Linux provides and which
must match the host (glibc, graphics drivers, ...).

Fails if a needed library can be neither found nor assumed present.
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
EXCLUDELIST = ROOT / "packaging" / "linux" / "excludelist"

ELF_MAGIC = b"\x7fELF"
# Each round copies libraries whose own dependencies may need another round.
MAX_ROUNDS = 10
# "libfoo.so.1 => /usr/lib64/libfoo.so.1 (0x...)" or "libfoo.so.1 => not found"
LDD_LINE = re.compile(r"^\s*(\S+)\s+=>\s+(not found|(\S+)\s+\(0x[0-9a-f]+\))\s*$")


def load_excludelist(path: Path = EXCLUDELIST) -> set[str]:
    lines = (line.split("#", 1)[0].strip() for line in path.read_text().splitlines())
    return {line for line in lines if line}


def parse_ldd(output: str) -> dict[str, str | None]:
    """Map each needed library to where the loader found it, or None if not found."""
    deps: dict[str, str | None] = {}
    for line in output.splitlines():
        match = LDD_LINE.match(line)
        if match:
            deps[match[1]] = match[3]
    return deps


class Plan(NamedTuple):
    to_copy: dict[str, Path]  # needed, found on the system, not in the folder yet
    relink: set[str]  # already in the folder, but this binary does not look there
    missing: set[str]  # needed and found nowhere


def plan(deps: dict[str, str | None], dist: Path, exclude: set[str]) -> Plan:
    """Decide what one binary still needs so that it only uses the folder and the host basics."""
    bundled = {path.name for path in dist.iterdir()} if dist.is_dir() else set[str]()
    result = Plan({}, set(), set())
    for name, location in deps.items():
        if name in exclude:
            continue
        if location is None:
            result.missing.add(name)
        elif Path(location).resolve().is_relative_to(dist.resolve()):
            continue
        elif name in bundled:
            result.relink.add(name)
        else:
            result.to_copy[name] = Path(location)
    return result


def elf_files(dist: Path) -> list[Path]:
    files: list[Path] = []
    for path in dist.rglob("*"):
        if path.is_file() and not path.is_symlink():
            with path.open("rb") as handle:
                if handle.read(4) == ELF_MAGIC:
                    files.append(path)
    return files


def direct_deps(binary: Path) -> dict[str, str | None]:
    """The libraries this file itself needs, and where the loader finds them.

    ldd lists the whole tree, including what host libraries (graphics drivers,
    fontconfig, ...) need; those are the host's business, so only the file's
    own NEEDED entries count.
    """
    needed = subprocess.run(
        ["patchelf", "--print-needed", str(binary)], capture_output=True, text=True, check=True
    ).stdout.split()
    result = subprocess.run(["ldd", str(binary)], capture_output=True, text=True, check=False)
    resolved = parse_ldd(result.stdout)
    return {name: resolved.get(name) for name in needed}


def add_rpath(binary: Path, directory: Path) -> None:
    relative = os.path.relpath(directory, binary.parent)
    entry = "$ORIGIN" if relative == "." else f"$ORIGIN/{relative}"
    current = subprocess.run(
        ["patchelf", "--print-rpath", str(binary)], capture_output=True, text=True, check=True
    ).stdout.strip()
    if entry not in current.split(":"):
        rpath = f"{current}:{entry}" if current else entry
        subprocess.run(["patchelf", "--set-rpath", rpath, str(binary)], check=True)


def bundle(dist: Path, exclude: set[str]) -> tuple[list[str], set[str]]:
    """Copy libraries in until nothing new is needed; return copied and missing names."""
    copied: list[str] = []
    relinked: set[Path] = set()
    for _ in range(MAX_ROUNDS):
        to_copy: dict[str, Path] = {}
        missing: set[str] = set()
        changed = False
        for binary in elf_files(dist):
            needs = plan(direct_deps(binary), dist, exclude)
            to_copy.update(needs.to_copy)
            missing |= needs.missing
            # Once is enough: if ldd still reports the system copy afterwards, a host
            # library loaded it first, and at run time the bundled copy wins anyway.
            if needs.relink and binary not in relinked:
                add_rpath(binary, dist)
                relinked.add(binary)
                changed = True
        for name, source in sorted(to_copy.items()):
            target = dist / name
            shutil.copy2(source.resolve(), target)
            # Let the copied library find its own dependencies next to it.
            subprocess.run(["patchelf", "--set-rpath", "$ORIGIN", str(target)], check=True)
            copied.append(name)
            changed = True
        if not changed:
            return copied, missing
    raise SystemExit(f"Libraries still unresolved after {MAX_ROUNDS} rounds")


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    dist = Path(argv[0])
    copied, missing = bundle(dist, load_excludelist())
    print(f"Bundled {len(copied)} libraries: {' '.join(sorted(copied))}")
    if missing:
        print("Needed but not found anywhere:", file=sys.stderr)
        for name in sorted(missing):
            print(f"  {name}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
