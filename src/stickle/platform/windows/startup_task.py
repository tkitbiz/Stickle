"""Starting at login from the Store package: its StartupTask, not a shortcut.

A packaged Stickle declares a StartupTask (see scripts/package_msix.py),
off until the user turns it on. Windows keeps its state, and the user can
turn it off in Task Manager or Settings, after which Stickle cannot turn it
on again by itself: enable() then fails, and the switch shows it off.

A shortcut left in the Startup folder by the zip build (pointing at a
program since deleted, or starting a second Stickle) is removed once the
packaged one runs.

Windows' answers are waited for on a thread of their own: the interface's
thread (a single-threaded apartment) may not wait for them. Anything going
wrong is an OSError, so starting at login never stops Stickle from starting.
"""

import logging
import sys
import threading
from collections.abc import Callable

from stickle.platform.autostart import Autostart

assert sys.platform == "win32"  # also tells the type checker the rest is Windows only

from winrt.windows.applicationmodel import AppInstance, StartupTask, StartupTaskState  # noqa: E402
from winrt.windows.applicationmodel.activation import ActivationKind  # noqa: E402

log = logging.getLogger(__name__)
TASK_ID = "StickleStartup"  # as declared in the package manifest
ON = (StartupTaskState.ENABLED, StartupTaskState.ENABLED_BY_POLICY)
WAIT_S = 10.0


def on_its_own_thread[T](work: Callable[[], T]) -> T:
    """work() on a thread that may wait for Windows; its error becomes an OSError."""
    outcome: list[T] = []
    failure: list[BaseException] = []

    def run() -> None:
        try:
            outcome.append(work())
        except BaseException as error:  # handed back to the caller below
            failure.append(error)

    thread = threading.Thread(target=run, name="startup-task", daemon=True)
    thread.start()
    thread.join(WAIT_S)
    if failure:
        raise OSError(f"{type(failure[0]).__name__}: {failure[0]}") from failure[0]
    if not outcome:
        raise OSError("Windows did not answer in time")
    return outcome[0]


def started_at_login() -> bool:
    """Whether Windows started this packaged Stickle for its StartupTask."""
    try:
        return AppInstance.get_activated_event_args().kind == ActivationKind.STARTUP_TASK
    except Exception:  # started some other way, with no arguments (None) to give
        return False


class PackagedAutostart(Autostart):
    """The same switch as Autostart, kept by Windows for the package."""

    def _task(self) -> StartupTask:
        return StartupTask.get_async(TASK_ID).get()

    @property
    def enabled(self) -> bool:
        try:
            return on_its_own_thread(lambda: self._task().state) in ON
        except OSError as error:
            log.warning("the startup task could not be read: %s", error)
            return False

    def enable(self) -> None:
        state = on_its_own_thread(lambda: self._task().request_enable_async().get())
        if state not in ON:
            # Turned off by the user in Windows' settings, or by policy: only there.
            raise PermissionError(f"the startup task stays {state.name.lower()}")

    def disable(self) -> None:
        on_its_own_thread(lambda: self._task().disable())

    def refresh(self) -> bool:
        """Remove a Startup folder shortcut left by the zip build; True if there was one."""
        legacy = super().path
        if not legacy.exists():
            return False
        legacy.unlink(missing_ok=True)
        log.info("a shortcut from an earlier Stickle was removed from the Startup folder")
        return True
