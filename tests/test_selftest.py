import subprocess
import sys

from stickle.selftest import run_checks


def test_all_checks_pass() -> None:
    assert all(ok for _, ok in run_checks()), run_checks()


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
