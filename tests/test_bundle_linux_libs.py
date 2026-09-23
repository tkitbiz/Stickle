from pathlib import Path

from bundle_linux_libs import load_excludelist, parse_ldd, plan

LDD_OUTPUT = """\
\tlinux-vdso.so.1 (0x00007ffd5b1e5000)
\tlibQt6Gui.so.6 => /app/dist/libQt6Gui.so.6 (0x00007f1c2a000000)
\tlibxcb-cursor.so.0 => /usr/lib64/libxcb-cursor.so.0 (0x00007f1c29e00000)
\tlibGL.so.1 => /usr/lib64/libGL.so.1 (0x00007f1c29c00000)
\tlibQt6Pdf.so.6 => not found
\tlibEGL.so.1 => not found
\t/lib64/ld-linux-x86-64.so.2 (0x00007f1c2a400000)
"""


def test_parse_ldd_reads_found_and_missing_libraries() -> None:
    assert parse_ldd(LDD_OUTPUT) == {
        "libQt6Gui.so.6": "/app/dist/libQt6Gui.so.6",
        "libxcb-cursor.so.0": "/usr/lib64/libxcb-cursor.so.0",
        "libGL.so.1": "/usr/lib64/libGL.so.1",
        "libQt6Pdf.so.6": None,
        "libEGL.so.1": None,
    }


def test_plan_copies_system_libraries_except_those_every_desktop_has(tmp_path: Path) -> None:
    deps = parse_ldd(LDD_OUTPUT.replace("/app/dist", str(tmp_path)))
    needs = plan(deps, tmp_path, {"libGL.so.1", "libEGL.so.1"})

    # Already in the folder: nothing to do. libGL/libEGL must come from the host's drivers.
    assert needs.to_copy == {"libxcb-cursor.so.0": Path("/usr/lib64/libxcb-cursor.so.0")}
    assert needs.relink == set()
    # Not found and not assumed present: the build is incomplete.
    assert needs.missing == {"libQt6Pdf.so.6"}


def test_plan_relinks_instead_of_copying_a_library_that_is_already_bundled(
    tmp_path: Path,
) -> None:
    # A binary in a subfolder resolves the system copy although the folder has one.
    (tmp_path / "libxcb-cursor.so.0").touch()
    deps: dict[str, str | None] = {"libxcb-cursor.so.0": "/usr/lib64/libxcb-cursor.so.0"}

    needs = plan(deps, tmp_path, set())

    assert needs.to_copy == {}
    assert needs.relink == {"libxcb-cursor.so.0"}


def test_excludelist_keeps_glibc_and_graphics_drivers_on_the_host() -> None:
    exclude = load_excludelist()

    assert {"libc.so.6", "libGL.so.1", "libEGL.so.1", "libfontconfig.so.1"} <= exclude
    assert "libxcb-cursor.so.0" not in exclude


def test_keyboard_tables_library_comes_from_the_host() -> None:
    # A bundled copy older than the host's compose files misreads them.
    assert {"libxkbcommon.so.0", "libxkbcommon-x11.so.0"} <= load_excludelist()
