from pathlib import Path

import pytest
from check_bundle import is_satisfied


@pytest.fixture
def system_dir(tmp_path: Path) -> Path:
    # Simulates a developer machine where the VC++ runtime was installed system-wide.
    for name in ["kernel32.dll", "user32.dll", "vcruntime140.dll", "msvcp140.dll"]:
        (tmp_path / name).touch()
    return tmp_path


@pytest.mark.parametrize("dll", ["KERNEL32.dll", "user32.dll", "api-ms-win-crt-runtime-l1-1-0.dll"])
def test_parts_of_windows_are_satisfied(system_dir: Path, dll: str) -> None:
    assert is_satisfied(dll, set(), system_dir)


@pytest.mark.parametrize("dll", ["VCRUNTIME140.dll", "vcruntime140_1.dll", "MSVCP140.dll"])
def test_redistributables_must_ship_even_if_installed_system_wide(
    system_dir: Path, dll: str
) -> None:
    assert not is_satisfied(dll, set(), system_dir)
    assert is_satisfied(dll, {dll.lower()}, system_dir)


def test_unknown_dll_is_missing(system_dir: Path) -> None:
    assert not is_satisfied("Qt6Core.dll", set(), system_dir)
    assert is_satisfied("Qt6Core.dll", {"qt6core.dll"}, system_dir)
