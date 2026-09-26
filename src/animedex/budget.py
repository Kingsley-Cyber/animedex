"""Pricing and budget caps (06 "ALL: Budget cap"): stop cleanly after the current unit."""

from __future__ import annotations

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
    run_cap: float
    per_title_cap: float
    per_episode_cap: float
    spent_run: float = 0.0
    spent_title: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    spent_episode: dict[str, float] = field(default_factory=lambda: defaultdict(float))

    @classmethod
    def from_settings(cls, settings: Settings) -> Budget:
        caps = []
        for key in ("run_cap_usd", "per_title_cap_usd", "per_episode_cap_usd"):
            value = settings.budget.get(key)
            if value is None or is_placeholder(value):
                raise BudgetConfigError(f"budget.{key} is not set; live runs are blocked")
            caps.append(float(value))
        return cls(*caps)

    def check(self, title_id: str | None = None, episode_id: str | None = None) -> None:
        """Call before starting a unit. Raises once any cap is reached."""
        if self.spent_run >= self.run_cap:
            raise BudgetExceeded(f"run cap ${self.run_cap:.2f} reached (spent ${self.spent_run:.4f})")
        if title_id and self.spent_title[title_id] >= self.per_title_cap:
            raise BudgetExceeded(f"title cap ${self.per_title_cap:.2f} reached for {title_id}")
        if episode_id and self.spent_episode[episode_id] >= self.per_episode_cap:
            raise BudgetExceeded(f"episode cap ${self.per_episode_cap:.2f} reached for {episode_id}")

    def charge(self, cost: float, title_id: str | None = None, episode_id: str | None = None) -> None:
        self.spent_run += cost
        if title_id:
            self.spent_title[title_id] += cost
        if episode_id:
            self.spent_episode[episode_id] += cost
