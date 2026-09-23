"""Measurement mode for scripts/measure.py (the hidden --perf-* options).

Start-up in this mode also does what the real start-up will do once notes are
stored: fetch the database key from the OS credential store and open an
encrypted database (a throwaway one in a temporary folder), so the measured
time includes them. Each phase is timed from the moment our code starts.
"""

import secrets
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from stickle.data.database import KEY_BYTES, open_database
from stickle.data.search import create_schema
from stickle.platform.credentials import CredentialStore, CredentialStoreUnavailableError


@dataclass
class PerfMode:
    notes: int
    blur: bool
    started: float  # time.perf_counter() when our code started
    storage: str = ""
    phases: list[tuple[str, float]] = field(default_factory=list[tuple[str, float]])

    def mark(self, phase: str) -> None:
        self.phases.append((phase, time.perf_counter() - self.started))

    def ready_line(self) -> str:
        """READY <storage> <phase>=<seconds since start>,..."""
        timings = ",".join(f"{phase}={seconds:.3f}" for phase, seconds in self.phases)
        return f"READY {self.storage} {timings}"


def open_storage_like_startup(perf: PerfMode) -> None:
    try:
        key = CredentialStore().get_or_create_key()
        perf.storage = "key-from-credential-store"
    except CredentialStoreUnavailableError:
        key = secrets.token_bytes(KEY_BYTES)
        perf.storage = "credential-store-unavailable"
    perf.mark("key")
    folder = Path(tempfile.mkdtemp(prefix="stickle-perf-"))
    try:
        connection = open_database(folder / "perf.db", key)
        create_schema(connection)
        connection.close()
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    perf.mark("database")
