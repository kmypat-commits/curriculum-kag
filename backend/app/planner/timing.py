"""Shared timing helper for planner stages."""

from __future__ import annotations

import time


class PlannerTimer:
    def __init__(self, label: str, *, enabled: bool = True) -> None:
        self.label = label
        self.started = time.perf_counter()
        self.enabled = enabled

    def trace(self, stage: str) -> None:
        if self.enabled:
            elapsed = time.perf_counter() - self.started
            print(f"{self.label} stage={stage} elapsed={elapsed:.2f}s", flush=True)
