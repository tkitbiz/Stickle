"""Check that encrypted storage, search and the credential store work here.

    stickle --self-test

The build pipeline runs this against the packaged app, because a native
library missing from a package only shows up at run time. Prints one line
per check (never paths, note text or keys) and returns 0 unless a check
fails. A missing credential store is reported as UNAVAILABLE, not as a
failure: build containers have none, and the app will ask for a password.
"""

import hashlib
import importlib
import secrets
import tempfile
from collections.abc import Callable
from pathlib import Path

from stickle.data.database import KEY_BYTES, WrongKeyError, open_database
from stickle.data.search import create_schema, search
from stickle.platform.credentials import (
    CredentialStore,
    CredentialStoreUnavailableError,
    bundled_support_modules,
)

SAMPLE = "회의록을 내일까지 작성"


def run_checks() -> list[tuple[str, str]]:
    """(status, name) pairs; status is PASS, FAIL, UNAVAILABLE or INFO."""
    results: list[tuple[str, str]] = []

    def check(name: str, test: Callable[[], bool]) -> None:
        try:
            ok = test()
        except Exception:
            ok = False
        results.append(("PASS" if ok else "FAIL", name))

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

    results += credential_checks()
    return results


def credential_checks() -> list[tuple[str, str]]:
    # A missing store is fine (the app asks for a password); a missing module is a
    # packaging bug and must fail even where no store is running.
    missing: list[str] = []
    for module in bundled_support_modules():
        try:
            importlib.import_module(module)
        except ImportError:
            missing.append(module)
    detail = f" (missing: {', '.join(missing)})" if missing else ""
    results = [("FAIL" if missing else "PASS", f"credential store support bundled{detail}")]
    try:
        store = CredentialStore()
    except CredentialStoreUnavailableError as error:
        return [*results, ("UNAVAILABLE", f"credential store ({error})")]
    name = f"self-test-{secrets.token_hex(4)}"
    secret = secrets.token_bytes(KEY_BYTES)
    try:
        store.write(name, secret)
        round_trip = store.read(name) == secret
        store.delete(name)
        gone = store.read(name) is None
        key = store.get_or_create_key()
    except CredentialStoreUnavailableError as error:
        return [*results, ("UNAVAILABLE", f"credential store ({error})")]
    # The first bytes of a hash identify the key across runs without revealing it.
    fingerprint = hashlib.sha256(key).hexdigest()[:8]
    return [
        *results,
        ("PASS" if round_trip and gone else "FAIL", "credential store round trip"),
        ("INFO", f"database key fingerprint {fingerprint}"),
    ]


def main() -> int:
    results = run_checks()
    for status, name in results:
        print(f"{status:<11} {name}")
    return 1 if any(status == "FAIL" for status, _ in results) else 0
