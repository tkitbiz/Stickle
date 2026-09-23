import pytest

from stickle.platform.linux.display import preferred_qt_platform

WAYLAND = {"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0"}


def test_wayland_session_runs_through_xwayland() -> None:
    assert preferred_qt_platform(WAYLAND) == "xcb"


def test_wayland_display_alone_counts_as_wayland() -> None:
    assert preferred_qt_platform({"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0"}) == "xcb"


@pytest.mark.parametrize(
    "env",
    [
        {"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"},  # already X11
        {"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "wayland-0"},  # no XWayland
        {**WAYLAND, "QT_QPA_PLATFORM": "wayland"},  # the user chose
        {**WAYLAND, "QT_QPA_PLATFORM": "offscreen"},
        {**WAYLAND, "STICKLE_NATIVE_WAYLAND": "1"},  # opted out
        {},
    ],
)
def test_otherwise_qt_decides(env: dict[str, str]) -> None:
    assert preferred_qt_platform(env) is None
