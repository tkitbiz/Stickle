import base64
import os
import subprocess
import sys
from pathlib import Path

import pytest

from stickle.platform.credentials import (
    DATABASE_KEY,
    CredentialStore,
    CredentialStoreUnavailableError,
)
from stickle.selftest import run_checks


def test_no_check_fails() -> None:
    results = run_checks()
    assert not [name for status, name in results if status == "FAIL"], results


def test_self_test_option_exits_cleanly_without_starting_the_ui() -> None:
    result = subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "stickle", "--self-test"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "FAIL" not in result.stdout
    # The output must not reveal note text.
    assert "회의록" not in result.stdout


def test_database_key_is_never_written_to_a_file(tmp_path: Path) -> None:
    # Every place the app could write to is redirected into tmp_path, then searched.
    folders = ["HOME", "APPDATA", "LOCALAPPDATA", "XDG_DATA_HOME", "XDG_CONFIG_HOME"]
    folders += ["XDG_CACHE_HOME", "XDG_STATE_HOME", "TMP", "TEMP", "TMPDIR"]
    env = {**os.environ, **{name: str(tmp_path / name) for name in folders}}
    for name in folders:
        (tmp_path / name).mkdir()
    subprocess.run(
        [sys.executable, "-m", "stickle", "--self-test"], env=env, check=True, timeout=60
    )
    try:
        key = CredentialStore().read(DATABASE_KEY)
    except CredentialStoreUnavailableError:
        pytest.skip("no credential store here")
    if key is None:
        pytest.skip("no database key was created")

    forms = [key, key.hex().encode(), key.hex().upper().encode(), base64.b64encode(key)]
    leaks = [
        str(path.relative_to(tmp_path))
        for path in tmp_path.rglob("*")
        if path.is_file() and any(form in path.read_bytes() for form in forms)
    ]
    assert leaks == []
