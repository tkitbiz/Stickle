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

from stickle.data.database import KEY_BYTES
from stickle.data.schema import open_store
from stickle.platform.credentials import CredentialStoreUnavailableError, KeyRequest

# Measured notes are formatted as real ones would be, so drawing them counts too.
SAMPLE_NOTE = (
    "# Shopping\n- [ ] milk **2**\n- [x] eggs\n\n오늘 ==꼭== 할 일\n"
    "1. call\n2. `mail`\n\n> a quote with *emphasis*"
)


@dataclass
class PerfMode:
    notes: int
    blur: bool
    started: float  # time.perf_counter() when our code started
    key_request: KeyRequest  # started before Qt was loaded
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
        # Only the time still spent waiting here counts: the request ran alongside start-up.
        key = perf.key_request.key()
        perf.storage = "key-from-credential-store"
    except CredentialStoreUnavailableError:
        key = secrets.token_bytes(KEY_BYTES)
        perf.storage = "credential-store-unavailable"
    perf.mark("key")
    folder = Path(tempfile.mkdtemp(prefix="stickle-perf-"))
    try:
        open_store(folder / "perf.db", key).close()
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    perf.mark("database")
