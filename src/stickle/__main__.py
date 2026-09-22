import argparse
import sys

from stickle import __version__


def main(argv: list[str] | None = None) -> int:
    args = sys.argv if argv is None else argv
    parser = argparse.ArgumentParser(prog="stickle")
    parser.add_argument("--version", action="version", version=f"Stickle {__version__}")
    # Unknown options are left for Qt (for example -platform).
    parser.parse_known_args(args[1:])

    from stickle.app.application import run

    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
