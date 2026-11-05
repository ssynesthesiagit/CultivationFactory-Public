from __future__ import annotations

import os
import threading
import uuid
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ProcessEpoch:
    """Identity for one operating-system process lifetime."""

    epoch_id: str
    process_id: int


class ProcessEpochProvider(Protocol):
    def current_epoch(self) -> ProcessEpoch: ...


class RuntimeProcessEpochProvider:
    """PID-aware process epoch shared by every service object in this process.

    A module-level provider is deliberate: ApprovalChallengeService objects are
    reconstructed by the API and service layers during one process lifetime.
    Object construction therefore cannot define the security epoch.  Forked or
    restarted processes receive a new random epoch when the PID changes.
    """

    _lock = threading.Lock()
    _process_id: int | None = None
    _epoch_id: str | None = None

    def current_epoch(self) -> ProcessEpoch:
        process_id = os.getpid()
        with self._lock:
            if self.__class__._process_id != process_id or self.__class__._epoch_id is None:
                self.__class__._process_id = process_id
                self.__class__._epoch_id = "process-epoch:" + str(uuid.uuid4())
            return ProcessEpoch(self.__class__._epoch_id, process_id)


class DeterministicTestProcessEpochProvider:
    """Explicit deterministic provider restricted to tests and sealed probes."""

    def __init__(self, epoch_id: str, process_id: int = 424242):
        if not epoch_id.startswith("test-process-epoch:"):
            raise ValueError("Deterministic process epochs must use the TEST-only prefix.")
        self._epoch = ProcessEpoch(epoch_id=epoch_id, process_id=int(process_id))

    def current_epoch(self) -> ProcessEpoch:
        return self._epoch


__all__ = [
    "DeterministicTestProcessEpochProvider",
    "ProcessEpoch",
    "ProcessEpochProvider",
    "RuntimeProcessEpochProvider",
]
