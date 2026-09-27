"""The call cap for the subscription CLIs: a run stops cleanly before the call that would pass it."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from animedex.config import Settings


class BudgetExceeded(RuntimeError):
    pass


class BudgetConfigError(RuntimeError):
    pass


@dataclass
class Budget:
    calls_per_run: int
    calls_run: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    @classmethod
    def from_settings(cls, settings: Settings) -> Budget:
        value = settings.budget.get("calls_per_run")
        if value is None:
            raise BudgetConfigError("budget.calls_per_run is not set; live runs are blocked")
        return cls(int(value))

    def check_calls(self) -> None:
        with self._lock:
            if self.calls_run >= self.calls_per_run:
                raise BudgetExceeded(f"call cap reached: {self.calls_run}/{self.calls_per_run} calls this run")

    def count_call(self) -> None:
        with self._lock:
            self.calls_run += 1
