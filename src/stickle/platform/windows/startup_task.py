"""Starting at login from the Store package: its StartupTask, not a shortcut.

A packaged Stickle declares a StartupTask (see scripts/package_msix.py),
off until the user turns it on. Windows keeps its state, and the user can
turn it off in Task Manager or Settings, after which Stickle cannot turn it
on again by itself: enable() then fails, and the switch shows it off.

A shortcut left in the Startup folder by the zip build (pointing at a
program since deleted, or starting a second Stickle) is removed once the
packaged one runs.
"""

import logging
import sys

from stickle.platform.autostart import Autostart

assert sys.platform == "win32"  # also tells the type checker the rest is Windows only

from winrt.windows.applicationmodel import AppInstance, StartupTask, StartupTaskState  # noqa: E402
from winrt.windows.applicationmodel.activation import ActivationKind  # noqa: E402

log = logging.getLogger(__name__)
TASK_ID = "StickleStartup"  # as declared in the package manifest
ON = (StartupTaskState.ENABLED, StartupTaskState.ENABLED_BY_POLICY)


def started_at_login() -> bool:
    """Whether Windows started this packaged Stickle for its StartupTask."""
    try:
        return AppInstance.get_activated_event_args().kind == ActivationKind.STARTUP_TASK
    except OSError:  # started some other way that has no arguments to give
        return False


class PackagedAutostart(Autostart):
    """The same switch as Autostart, kept by Windows for the package."""

    def _task(self) -> StartupTask:
        return StartupTask.get_async(TASK_ID).get()

    @property
    def enabled(self) -> bool:
        try:
            return self._task().state in ON
        except OSError:
            return False

    def enable(self) -> None:
        state = self._task().request_enable_async().get()
        if state not in ON:
            # Turned off by the user in Windows' settings, or by policy: only there.
            raise PermissionError(f"the startup task stays {state.name.lower()}")

    def disable(self) -> None:
        self._task().disable()

    def refresh(self) -> bool:
        """Remove a Startup folder shortcut left by the zip build; True if there was one."""
        legacy = super().path
        if not legacy.exists():
            return False
        legacy.unlink(missing_ok=True)
        log.info("a shortcut from an earlier Stickle was removed from the Startup folder")
        return True
