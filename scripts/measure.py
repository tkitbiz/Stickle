"""Measure start-up time, memory and idle CPU of a built Stickle.

    python measure.py build/stickle.dist/stickle.exe
    python3 /mnt/share/measure.py ~/Stickle-x86_64.AppImage

Uses the standard library only, so it runs on a test machine as it is.
Targets: 20 notes in at most 200 MB, start-up within 2 s, no CPU when idle.
The first run is reported separately: right after a reboot it is the cold
start, with nothing in the disk cache.
"""

import argparse
import contextlib
import ctypes
import os
import signal
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

MEMORY_LIMIT_MB = 200
STARTUP_LIMIT_S = 2.0
SETTLE_S = 3.0


@dataclass
class Sample:
    rss_mb: float  # working set (Windows) / resident set (Linux): the generous figure
    own_mb: float  # private commit (Windows) / proportional set (Linux): the app's own share
    cpu_s: float
    wakeups: int | None  # context switches of all threads (Linux only)


# ---- per-platform process inspection -------------------------------------------------


def linux_sample(pid: int) -> Sample:
    status = Path(f"/proc/{pid}/status").read_text()
    rss_kb = int(next(line.split()[1] for line in status.splitlines() if line.startswith("VmRSS")))
    rollup = Path(f"/proc/{pid}/smaps_rollup").read_text()
    pss_kb = int(next(line.split()[1] for line in rollup.splitlines() if line.startswith("Pss:")))
    fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    ticks: int = getattr(os, "sysconf")("SC_CLK_TCK")  # noqa: B009 - Unix only
    cpu = (int(fields[11]) + int(fields[12])) / ticks  # utime + stime
    wakeups = 0
    for task in Path(f"/proc/{pid}/task").iterdir():
        for line in (task / "status").read_text().splitlines():
            if line.startswith(("voluntary_ctxt_switches", "nonvoluntary_ctxt_switches")):
                wakeups += int(line.split()[1])
    return Sample(rss_kb / 1024, pss_kb / 1024, cpu, wakeups)


def linux_app_pid(launcher: int) -> int:
    """The stickle.bin process, which an AppImage starts as a child of its runtime."""
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        for proc in Path("/proc").iterdir():
            if not proc.name.isdigit():
                continue
            try:
                if (proc / "comm").read_text().strip() != "stickle.bin":
                    continue
                stat = (proc / "stat").read_text().rsplit(")", 1)[1].split()
            except OSError:
                continue
            if int(proc.name) == launcher or int(stat[1]) == launcher:
                return int(proc.name)
        time.sleep(0.1)
    raise RuntimeError("stickle.bin process not found")


class ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


def windows_sample(pid: int) -> Sample:
    windll = getattr(ctypes, "windll")  # noqa: B009 - only exists on Windows
    handle = windll.kernel32.OpenProcess(0x1000 | 0x0010, False, pid)  # query limited | VM read
    try:
        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
        times = [ctypes.c_ulonglong() for _ in range(4)]
        windll.kernel32.GetProcessTimes(handle, *(ctypes.byref(t) for t in times))
        cpu = (times[2].value + times[3].value) / 1e7  # kernel + user, 100 ns units
    finally:
        windll.kernel32.CloseHandle(handle)
    mb = 1024 * 1024
    return Sample(counters.WorkingSetSize / mb, counters.PrivateUsage / mb, cpu, None)


def sample(pid: int) -> Sample:
    return windows_sample(pid) if sys.platform == "win32" else linux_sample(pid)


# ---- one run -------------------------------------------------------------------------


@dataclass
class Run:
    startup_s: float
    storage: str
    memory: Sample
    idle_cpu_s: float | None = None
    idle_wakeups: int | None = None


def run_once(app: Path, notes: int, idle_s: float = 0) -> Run:
    start = time.perf_counter()
    command = [str(app), "--perf-notes", str(notes)]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, text=True)
    try:
        assert process.stdout is not None
        line = ""
        while not line.startswith("READY"):
            line = process.stdout.readline()
            if not line:
                raise RuntimeError("app exited before it was ready")
        startup = time.perf_counter() - start
        pid = process.pid if sys.platform == "win32" else linux_app_pid(process.pid)
        time.sleep(SETTLE_S)
        before = sample(pid)
        result = Run(startup, line.split()[1] if len(line.split()) > 1 else "", before)
        if idle_s:
            time.sleep(idle_s)
            after = sample(pid)
            result.idle_cpu_s = after.cpu_s - before.cpu_s
            if after.wakeups is not None and before.wakeups is not None:
                result.idle_wakeups = after.wakeups - before.wakeups
        return result
    finally:
        stop(process)


def stop(process: subprocess.Popen[str]) -> None:
    if sys.platform != "win32":
        # The AppImage runtime does not pass signals on, so end its child as well.
        with contextlib.suppress(RuntimeError, OSError):
            os.kill(linux_app_pid(process.pid), signal.SIGTERM)
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


# ---- report --------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("app", type=Path)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--idle", type=float, default=30)
    options = parser.parse_args(argv)
    app: Path = options.app

    print(f"Stickle performance  ({sys.platform}, {time.strftime('%Y-%m-%d %H:%M')})")
    first = run_once(app, 1)
    print(f"first run start-up    {first.startup_s:5.2f} s   (cold if right after a reboot)")
    print(f"storage at start-up   {first.storage}")

    warm = [run_once(app, 1).startup_s for _ in range(options.runs)]
    median = statistics.median(warm)
    runs = ", ".join(f"{s:.2f}" for s in warm)
    print(f"start-up, median of {options.runs}  {median:5.2f} s   (runs: {runs})")

    print("notes   memory MB (generous / own)")
    by_notes: dict[int, Run] = {}
    for notes in (1, 5, 10, 20):
        idle = options.idle if notes == 20 else 0
        by_notes[notes] = run_once(app, notes, idle)
        m = by_notes[notes].memory
        print(f"{notes:5d}   {m.rss_mb:7.1f} / {m.own_mb:6.1f}")

    idle_run = by_notes[20]
    idle_cpu = idle_run.idle_cpu_s or 0.0
    share = 100 * idle_cpu / options.idle
    wakeups = f", {idle_run.idle_wakeups} wake-ups" if idle_run.idle_wakeups is not None else ""
    print(f"idle {options.idle:.0f} s with 20 notes: CPU {idle_cpu:.3f} s ({share:.2f} %){wakeups}")

    memory_ok = idle_run.memory.rss_mb <= MEMORY_LIMIT_MB
    startup_ok = median <= STARTUP_LIMIT_S
    print(f"memory 20 notes <= {MEMORY_LIMIT_MB} MB: {'PASS' if memory_ok else 'FAIL'}")
    print(f"start-up <= {STARTUP_LIMIT_S:.0f} s: {'PASS' if startup_ok else 'FAIL'}")
    return 0 if memory_ok and startup_ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
