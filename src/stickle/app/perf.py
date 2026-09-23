"""Measurement mode for scripts/measure.py (the hidden --perf-notes option).

Start-up in this mode also does what the real start-up will do once notes are
stored: fetch the database key from the OS credential store and open an
encrypted database (a throwaway one in a temporary folder), so the measured
time includes them.
"""

import secrets
import shutil
import tempfile
from pathlib import Path

from stickle.data.database import KEY_BYTES, open_database
from stickle.data.search import create_schema
from stickle.platform.credentials import CredentialStore, CredentialStoreUnavailableError


def open_storage_like_startup() -> str:
    """Return how the key was obtained, for the READY line."""
    try:
        key = CredentialStore().get_or_create_key()
        source = "key-from-credential-store"
    except CredentialStoreUnavailableError:
        key = secrets.token_bytes(KEY_BYTES)
        source = "credential-store-unavailable"
    folder = Path(tempfile.mkdtemp(prefix="stickle-perf-"))
    try:
        connection = open_database(folder / "perf.db", key)
        create_schema(connection)
        connection.close()
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    return source
