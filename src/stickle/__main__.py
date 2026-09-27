import argparse
import os
import sys
import time

from stickle import __version__


def main(argv: list[str] | None = None) -> int:
    started = time.perf_counter()
    args = sys.argv if argv is None else argv
    parser = argparse.ArgumentParser(prog="stickle")
    parser.add_argument("--version", action="version", version=f"Stickle {__version__}")
    parser.add_argument("--self-test", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--perf-notes", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--perf-blur", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--screens", action="store_true", help=argparse.SUPPRESS)
    # Started at login (see stickle.platform.autostart): no window of its own at start.
    parser.add_argument("--autostart", action="store_true", help=argparse.SUPPRESS)
    # Unknown options are left for Qt (for example -platform).
    options, _ = parser.parse_known_args(args[1:])
    if options.self_test:
        from stickle.selftest import main as self_test

        return self_test()
    if options.screens:
        from stickle.app.screens import report

        return report(args)

    if options.perf_notes is not None:
        from stickle.platform.credentials import KeyRequest

        # Before Qt is loaded below, so that the two overlap. A key of its own, so
        # measuring never creates or touches the key of the real notes.
        key_request = KeyRequest("perf-database-key")
        from stickle.app.perf import PerfMode

        perf = PerfMode(options.perf_notes, options.perf_blur, started, key_request)
        from stickle.app.application import run

        return run(args, perf)

    import logging

    from stickle.logs import setup_logging
    from stickle.platform.paths import data_dir, ensure_private_dir
    from stickle.unlock import Unlock

    folder = data_dir()
    warnings = ensure_private_dir(folder)
    from stickle.platform.instance import InstanceLock, ask_to_show

    # Before anything else touches the data folder: one Stickle per user and folder.
    lock = InstanceLock(folder)
    if not lock.acquire():
        if ask_to_show(folder):
            return 0
        # Nobody answered: the holder has gone (Windows lets go of a crashed
        # process's lock a moment later), so this one starts instead.
        if not lock.acquire():
            return 1
    setup_logging(folder / "logs", data=folder)
    log = logging.getLogger("stickle")
    log.info("Stickle %s starting", __version__)
    for warning in warnings:
        log.warning(warning)
    # Before Qt is loaded below, so that a credential store lookup overlaps it.
    unlock = Unlock(folder)

    from stickle.app.application import ended_by_signal, run
    from stickle.data.startup import StartupSettings

    try:
        code = run(
            args,
            unlock=unlock,
            started=started,
            startup=StartupSettings(folder),
            instance=folder,
            at_login=options.autostart,
        )
    finally:
        lock.release()
    if os.environ.get("APPIMAGE") and ended_by_signal():
        # An AppImage runs from files its launcher serves; a shutdown ends the
        # launcher at the same moment, and the usual clean-up would then read
        # code that is no longer there and crash. The notes are saved and
        # closed by now, so end here.
        log.info("ending at once: the AppImage's files may be gone")
        logging.shutdown()
        os._exit(code)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
