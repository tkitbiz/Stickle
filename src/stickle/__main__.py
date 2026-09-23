import argparse
import sys

from stickle import __version__


def main(argv: list[str] | None = None) -> int:
    args = sys.argv if argv is None else argv
    parser = argparse.ArgumentParser(prog="stickle")
    parser.add_argument("--version", action="version", version=f"Stickle {__version__}")
    parser.add_argument("--self-test", action="store_true", help=argparse.SUPPRESS)
    # Unknown options are left for Qt (for example -platform).
    options, _ = parser.parse_known_args(args[1:])
    if options.self_test:
        from stickle.selftest import main as self_test

        return self_test()

    from stickle.app.application import run

    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
