"""Choose how the app connects to the display on Linux."""

from collections.abc import Mapping

# Set to 1 to run as a native Wayland client anyway (until settings exist).
NATIVE_WAYLAND_SWITCH = "STICKLE_NATIVE_WAYLAND"


def preferred_qt_platform(env: Mapping[str, str]) -> str | None:
    """Return "xcb" when a Wayland session should run the app through XWayland.

    Wayland does not let applications keep a window above the others or place
    it on screen, so notes would lose always-on-top and their remembered
    positions. XWayland allows both. None leaves Qt's own choice alone: the
    session is not Wayland, XWayland is unavailable, or the user decided.
    """
    if env.get("QT_QPA_PLATFORM") or env.get(NATIVE_WAYLAND_SWITCH) == "1":
        return None
    wayland = env.get("XDG_SESSION_TYPE") == "wayland" or bool(env.get("WAYLAND_DISPLAY"))
    if wayland and env.get("DISPLAY"):
        return "xcb"
    return None
