import pytest

from stickle.app.screens import mask


@pytest.mark.parametrize(
    ("serial", "shown"),
    [
        ("", "(empty)"),
        ("   ", "(empty)"),
        ("0000000", "(zeros, 7 chars)"),
        ("AB12", "**** (4 chars)"),
        ("ABC123456XY", "AB*******XY (11 chars)"),
    ],
)
def test_serials_are_masked(serial: str, shown: str) -> None:
    assert mask(serial) == shown


def test_a_real_serial_never_appears_whole() -> None:
    assert "123456" not in mask("ABC123456XY")
