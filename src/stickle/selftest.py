"""Check that encrypted storage and search work in this installation.

    stickle --self-test

The build pipeline runs this against the packaged app, because a native
library missing from a package only shows up at run time. Prints one line
per check (never paths or note text) and returns 0 when all pass.
"""

import secrets
import tempfile
from collections.abc import Callable
from pathlib import Path

from stickle.data.database import KEY_BYTES, WrongKeyError, open_database
from stickle.data.search import create_schema, search

SAMPLE = "회의록을 내일까지 작성"


def run_checks() -> list[tuple[str, bool]]:
    results: list[tuple[str, bool]] = []

    def check(name: str, test: Callable[[], bool]) -> None:
        try:
            results.append((name, test()))
        except Exception:
            results.append((name, False))

    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        path = folder / "selftest.db"
        key = secrets.token_bytes(KEY_BYTES)
        connection = open_database(path, key)
        create_schema(connection)
        with connection:
            connection.execute("INSERT INTO notes(id, body) VALUES ('a', ?)", (SAMPLE,))

        check("encrypted database opens and stores text", lambda: True)
        # A particle attached (회의록을) and a term below the trigram length (회의).
        check("trigram search", lambda: search(connection, "회의록") == ["a"])
        check("short-term search", lambda: search(connection, "회의") == ["a"])

        def no_plaintext() -> bool:
            return all(SAMPLE.encode() not in f.read_bytes() for f in folder.iterdir())

        check("no plaintext on disk", no_plaintext)
        connection.close()

        def wrong_key_rejected() -> bool:
            try:
                open_database(path, secrets.token_bytes(KEY_BYTES)).close()
            except WrongKeyError:
                return True
            return False

        check("wrong key is rejected", wrong_key_rejected)
    return results


def main() -> int:
    results = run_checks()
    for name, ok in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    return 0 if all(ok for _, ok in results) else 1
