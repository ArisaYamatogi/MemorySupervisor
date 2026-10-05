"""Memory sampling.

A single background thread polls the Win32 memory counters and publishes an
immutable snapshot.  The UI thread only ever reads the latest snapshot, so the
polling interval can be short without the panel's own drawing being able to
slow it down (or vice versa).
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field

from . import platform_win as pw

GIB = 1024.0 ** 3


@dataclass(frozen=True, slots=True)
class MemorySnapshot:
    """One consistent reading of the machine's memory state."""

    timestamp: float = 0.0
    total_bytes: int = 0
    used_bytes: int = 0
    avail_bytes: int = 0
    commit_total: int = 0
    commit_limit: int = 0
    phys_total_page: int = 0
    process_count: int = 0
    thread_count: int = 0
    handle_count: int = 0
    valid: bool = False

    @property
    def percent(self) -> float:
        return (self.used_bytes / self.total_bytes * 100.0) if self.total_bytes else 0.0

    @property
    def commit_percent(self) -> float:
        return (self.commit_total / self.commit_limit * 100.0) if self.commit_limit else 0.0

    @property
    def total_gib(self) -> float:
        return self.total_bytes / GIB

    @property
    def used_gib(self) -> float:
        return self.used_bytes / GIB

    @property
    def avail_gib(self) -> float:
        return self.avail_bytes / GIB

    @property
    def commit_used_gib(self) -> float:
        return self.commit_total / GIB

    @property
    def commit_limit_gib(self) -> float:
        return self.commit_limit / GIB


def read_memory() -> MemorySnapshot:
    """Read the current memory state synchronously (about 50 microseconds)."""
    status = pw.query_memory_status()
    if status is None:
        return MemorySnapshot(timestamp=time.monotonic())

    total = int(status.ullTotalPhys)
    avail = int(status.ullAvailPhys)
    used = max(0, total - avail)

    commit_total = commit_limit = 0
    page_count = 0
    processes = threads = handles = 0
    perf = pw.query_performance_info()
    if perf is not None:
        page = int(perf.PageSize) or 4096
        commit_total = int(perf.CommitTotal) * page
        commit_limit = int(perf.CommitLimit) * page
        page_count = page
        processes = int(perf.ProcessCount)
        threads = int(perf.ThreadCount)
        handles = int(perf.HandleCount)

    return MemorySnapshot(
        timestamp=time.monotonic(),
        total_bytes=total,
        used_bytes=used,
        avail_bytes=avail,
        commit_total=commit_total,
        commit_limit=commit_limit,
        phys_total_page=page_count,
        process_count=processes,
        thread_count=threads,
        handle_count=handles,
        valid=True,
    )


@dataclass
class History:
    """Rolling window of usage percentages, newest last."""

    capacity: int = 90
    values: deque = field(default_factory=lambda: deque(maxlen=90))

    def __post_init__(self) -> None:
        if self.values.maxlen != self.capacity:
            self.values = deque(self.values, maxlen=self.capacity)

    def resize(self, capacity: int) -> None:
        if capacity == self.capacity:
            return
        self.capacity = capacity
        self.values = deque(self.values, maxlen=capacity)

    def push(self, percent: float) -> None:
        self.values.append(percent)

    def as_list(self) -> list[float]:
        return list(self.values)

    def __len__(self) -> int:
        return len(self.values)


class Sampler:
    """Background poller that keeps the newest snapshot available."""

    def __init__(self, interval: float = 0.5, history_size: int = 90,
                 history_interval: float = 1.0) -> None:
        self.interval = max(0.1, float(interval))
        self.history = History(capacity=history_size)
        self._history_interval = max(self.interval, float(history_interval))
        self._lock = threading.Lock()
        self._snapshot = MemorySnapshot()
        self._samples = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_history = 0.0

    # -- lifecycle --------------------------------------------------------- #
    def start(self) -> None:
        if self._thread is not None:
            return
        self._snapshot = read_memory()
        self._thread = threading.Thread(target=self._run, name="memsup-sampler",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            snap = read_memory()
            now = snap.timestamp
            with self._lock:
                self._snapshot = snap
                self._samples += 1
            if now - self._last_history >= self._history_interval:
                self._last_history = now
                self.history.push(snap.percent)
            self._stop.wait(self.interval)

    # -- accessors --------------------------------------------------------- #
    def snapshot(self) -> MemorySnapshot:
        with self._lock:
            return self._snapshot

    @property
    def sample_count(self) -> int:
        with self._lock:
            return self._samples
