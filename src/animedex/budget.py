"""Pricing and budget caps (06 "ALL: Budget cap"): stop cleanly after the current unit."""

from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass, field

from animedex.config import Settings, is_placeholder


class BudgetExceeded(RuntimeError):
    pass


class BudgetConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Price:
    input_per_mtok: float
    output_per_mtok: float

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * self.input_per_mtok + output_tokens * self.output_per_mtok) / 1_000_000


def price_for(settings: Settings, provider: str, model: str) -> Price | None:
    entry = settings.pricing.get(f"{provider}/{model}")
    if not entry:
        return None
    try:
        return Price(float(entry["input_per_mtok"]), float(entry["output_per_mtok"]))
    except (KeyError, TypeError, ValueError):
        return None


@dataclass
class Budget:
    """Dollar caps for API-billed providers; call caps for subscription CLIs (G1a), whose reported
    cost is logged as a shadow cost but never charged."""

    run_cap: float | None
    per_title_cap: float | None
    per_episode_cap: float | None
    calls_per_run: int | None = None
    calls_per_title: int | None = None
    spent_run: float = 0.0
    spent_title: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    spent_episode: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    calls_run: int = 0
    calls_title: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)   # v1.10: shared by workers

    @classmethod
    def from_settings(cls, settings: Settings) -> Budget:
        """Unset caps stay None; the check for the billing kind in use refuses to run without them."""
        caps: list[float | None] = []
        for key in ("run_cap_usd", "per_title_cap_usd", "per_episode_cap_usd"):
            value = settings.budget.get(key)
            caps.append(None if value is None or is_placeholder(value) else float(value))
        calls: list[int | None] = []
        for key in ("calls_per_run", "calls_per_title"):
            value = settings.budget.get(key)
            calls.append(None if value is None or is_placeholder(value) else int(value))
        if None in caps and None in calls:
            raise BudgetConfigError("budget caps are not set (dollar caps for API providers, call caps for CLI "
                                    "providers); live runs are blocked")
        return cls(*caps, *calls)

    def check_calls(self, title_id: str | None = None) -> None:
        """Subscription calls: stop before a call that would pass the per-run or per-title cap."""
        if self.calls_per_run is None or self.calls_per_title is None:
            raise BudgetConfigError("budget.calls_per_run / calls_per_title are not set; CLI runs are blocked")
        with self._lock:
            if self.calls_run >= self.calls_per_run:
                raise BudgetExceeded(f"call cap reached: {self.calls_run}/{self.calls_per_run} calls this run")
            if title_id and self.calls_title[title_id] >= self.calls_per_title:
                raise BudgetExceeded(f"call cap reached for {title_id}: {self.calls_per_title} calls")

    def count_call(self, title_id: str | None = None) -> None:
        with self._lock:
            self.calls_run += 1
            if title_id:
                self.calls_title[title_id] += 1

    def check(self, title_id: str | None = None, episode_id: str | None = None) -> None:
        """API-billed calls: call before starting a unit. Raises once any cap is reached."""
        if self.run_cap is None or self.per_title_cap is None or self.per_episode_cap is None:
            raise BudgetConfigError("budget dollar caps are not set; API-billed live runs are blocked")
        if self.spent_run >= self.run_cap:
            raise BudgetExceeded(f"run cap ${self.run_cap:.2f} reached (spent ${self.spent_run:.4f})")
        if title_id and self.spent_title[title_id] >= self.per_title_cap:
            raise BudgetExceeded(f"title cap ${self.per_title_cap:.2f} reached for {title_id}")
        if episode_id and self.spent_episode[episode_id] >= self.per_episode_cap:
            raise BudgetExceeded(f"episode cap ${self.per_episode_cap:.2f} reached for {episode_id}")

    def charge(self, cost: float, title_id: str | None = None, episode_id: str | None = None) -> None:
        with self._lock:
            self.spent_run += cost
            if title_id:
                self.spent_title[title_id] += cost
            if episode_id:
                self.spent_episode[episode_id] += cost
