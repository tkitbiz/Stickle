import argparse
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
    # Unknown options are left for Qt (for example -platform).
    options, _ = parser.parse_known_args(args[1:])
    if options.self_test:
        from stickle.selftest import main as self_test

        return self_test()
    if options.screens:
        from stickle.app.screens import report

        return report(args)

    perf = None
    if options.perf_notes is not None:
        from stickle.platform.credentials import KeyRequest

        # Before Qt is loaded below, so that the two overlap.
        key_request = KeyRequest()
        from stickle.app.perf import PerfMode

        perf = PerfMode(options.perf_notes, options.perf_blur, started, key_request)

    from stickle.app.application import run

    return run(args, perf)


if __name__ == "__main__":
    raise SystemExit(main())
