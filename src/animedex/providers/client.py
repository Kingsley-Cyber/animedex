"""LLMClient: the one path every pass uses to call a model.

complete(system, user, json_schema, params) -> (json, usage)   (03 provider interface)

Order of operations:
1. cache lookup (key per 05, model part = provider identity, e.g. `claude_cli@2.1.251/<model>`);
   a hit spends nothing;
2. live calls only: title guard (corpus scope + gold blind guard), then the budget: dollar caps for
   API-billed providers, call caps for subscription CLIs (G1a);
3. provider call; JSON parse + validation; on failure, ONE repair call with the error (11),
   then InvalidOutput (the stage quarantines);
4. every attempt is logged with fetched web text redacted. API calls are charged; subscription
   calls are counted and their reported cost is logged as a shadow cost.
A response served by a different model than requested is recorded but never cached; strict slots
refuse it outright.
"""

from __future__ import annotations

import inspect
import json
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from pydantic import ValidationError

from animedex.budget import Budget, Price
from animedex.config import ModelSpec
from animedex.providers.base import Provider, ProviderError, Usage, same_model
from animedex.providers.cli_common import unexpected_loads
from animedex.store.cache import ResponseCache, cache_key
from animedex.store.runlog import RunLog, TransientText

REPAIR_SUFFIX = (
    "\n\nYour previous reply was rejected: {error}\n"
    "Return one corrected JSON object only, matching the schema."
)
_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


class ClientConfigError(RuntimeError):
    pass


class ModelSubstituted(ProviderError):
    """A strict slot (CHECK, judge) was answered by a different model; the output is refused."""


class InvalidOutput(RuntimeError):
    def __init__(self, errors: list[str], raw: str):
        self.errors = errors
        self.raw = raw
        super().__init__("model output invalid after one repair: " + " | ".join(e[:300] for e in errors))


def parse_json(text: str) -> dict[str, Any]:
    m = _FENCE.match(text)
    if m:
        text = m.group(1)
    text = text.strip()
    if not text.startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("no JSON object in the reply")
        text = text[start : end + 1]
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("reply must be a JSON object")
    return data


@dataclass(frozen=True)
class CallContext:
    pass_: str
    record_id: str
    upstream: str
    title_id: str | None = None
    episode_id: str | None = None
    transients: tuple[TransientText, ...] = field(default_factory=tuple)
    meta: dict[str, Any] | None = None  # logged with every attempt (e.g. the M5 call brief's size); not in the key


@dataclass(frozen=True)
class Completion:
    data: dict[str, Any]
    usage: Usage
    model: str          # the model that actually served the call
    cache_key: str
    cache_hit: bool
    substituted: bool = False  # served by a different model than requested; never cached
    identity: str = ""         # provider identity, e.g. claude_cli@2.1.251
    meta: dict[str, Any] = field(default_factory=dict)  # persisted provider evidence, e.g. {"web": {...}}

    @property
    def provenance_model(self) -> str:
        """What goes in provenance.model: provider identity (CLI name + version) + served model."""
        return f"{self.identity}/{self.model}" if self.identity else self.model


KEPT_META = ("web",)  # provider evidence worth caching (URLs and counts, never page text)


def _required_args(fn: Callable[..., Any]) -> int:
    try:
        params = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        return 1
    return sum(1 for p in params if p.default is p.empty and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD))


def run_validate(validate: Callable[..., Any] | None, data: dict[str, Any], meta: dict[str, Any]) -> None:
    """`validate(data)`, or `validate(data, meta)` when it takes two required args (VERIFY checks
    citations against the call's own web evidence)."""
    if validate is None:
        return
    if _required_args(validate) >= 2:
        validate(data, meta)
    else:
        validate(data)


class LLMClient:
    def __init__(
        self,
        *,
        provider: Provider,
        provider_name: str,
        spec: ModelSpec,
        prompt_version: str,
        schema_version: str,
        vocab_version: str,
        cache: ResponseCache,
        runlog: RunLog,
        price: Price | None = None,
        budget: Budget | None = None,
        title_guard: Callable[[str], None] | None = None,
        min_interval_s: float = 0.0,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.billing = getattr(provider, "billing", "api")
        if provider.live:
            missing = [n for n, v in (("budget", budget), ("title guard", title_guard)) if v is None]
            if self.billing == "api" and price is None:
                missing.append("pricing")
            if missing:
                raise ClientConfigError(f"live provider {provider_name}/{spec.model} needs {', '.join(missing)}")
        self.provider = provider
        self.provider_name = provider_name
        self.identity = str(getattr(provider, "identity", provider_name))
        self.spec = spec
        self.prompt_version = prompt_version
        self.schema_version = schema_version
        self.vocab_version = vocab_version
        self.cache = cache
        self.runlog = runlog
        self.price = price
        self.budget = budget
        self.title_guard = title_guard
        self.min_interval_s = min_interval_s
        self._sleep = sleep
        self._last_call: float | None = None

    def key_for(self, ctx: CallContext, params: dict[str, Any] | None = None) -> str:
        merged = {**self.spec.params, **(params or {})}
        return cache_key(
            record_id=ctx.record_id,
            pass_=ctx.pass_,
            prompt_version=self.prompt_version,
            schema_version=self.schema_version,
            vocab_version=self.vocab_version,
            model=f"{self.identity}/{self.spec.model}",
            params=merged,
            upstream=ctx.upstream,
        )

    def complete(
        self,
        system: str,
        user: str,
        json_schema: dict[str, Any],
        params: dict[str, Any] | None = None,
        *,
        ctx: CallContext,
        validate: Callable[[dict[str, Any]], Any] | None = None,
    ) -> tuple[dict[str, Any], Usage]:
        result = self.complete_ex(system, user, json_schema, params, ctx=ctx, validate=validate)
        return result.data, result.usage

    def _pace(self) -> float:
        """Sleep out the gap between calls; returns the seconds slept (logged as pacing)."""
        waited = 0.0
        if self.min_interval_s and self._last_call is not None:
            wait = self.min_interval_s - (time.monotonic() - self._last_call)
            if wait > 0:
                self._sleep(wait)
                waited = wait
        self._last_call = time.monotonic()
        return waited

    def _check_budget(self, ctx: CallContext) -> None:
        if not self.provider.live or self.budget is None:
            return
        if self.billing == "subscription":
            self.budget.check_calls(ctx.title_id)
        else:
            self.budget.check(ctx.title_id, ctx.episode_id)

    def complete_ex(
        self,
        system: str,
        user: str,
        json_schema: dict[str, Any],
        params: dict[str, Any] | None = None,
        *,
        ctx: CallContext,
        validate: Callable[..., Any] | None = None,
    ) -> Completion:
        key = self.key_for(ctx, params)
        log_common = {"pass_": ctx.pass_, "record_id": ctx.record_id, "provider": self.identity,
                      "cache_key": key, "system": system, "transients": ctx.transients, "billing": self.billing,
                      "extra": ctx.meta}

        hit = self.cache.get(ctx.pass_, key)
        if hit is not None:
            self.runlog.log_call(**log_common, model=hit.get("model", ""), cache_hit=True, attempt=0,
                                 input_tokens=0, output_tokens=0, cost_usd=0.0, user=user,
                                 response=json.dumps(hit["json"], sort_keys=True))
            return Completion(hit["json"], Usage(), hit.get("model", ""), key, True, False,
                              hit.get("identity", self.identity), hit.get("meta") or {})

        if self.provider.live and ctx.title_id:
            self.title_guard(ctx.title_id)  # type: ignore[misc]

        call_params = {**self.spec.params, **(params or {}), "model": self.spec.model}
        total = Usage()
        errors: list[str] = []
        attempt_user = user
        for attempt in (0, 1):
            self._check_budget(ctx)
            sent = dict(call_params)
            if not self.provider.live:
                sent["_meta"] = {"pass": ctx.pass_, "record_id": ctx.record_id, "attempt": attempt}
            paced = self._pace()
            started = time.monotonic()
            try:
                resp = self.provider.generate(system, attempt_user, json_schema, sent)
            except ProviderError as exc:
                if self.provider.live and self.billing == "subscription" and self.budget is not None:
                    self.budget.count_call(ctx.title_id)
                self.runlog.log_call(**log_common, model=self.spec.model, cache_hit=False, attempt=attempt,
                                     input_tokens=0, output_tokens=0, cost_usd=0.0, user=attempt_user,
                                     response=None, error=str(exc),
                                     timing={"call_s": round(time.monotonic() - started, 2), "pacing_s": round(paced, 2)})
                raise
            timing = {**(resp.meta.get("timing") or {}), "call_s": round(time.monotonic() - started, 2),
                      "pacing_s": round(paced, 2)}
            if self.billing == "subscription":
                cost = float(resp.meta.get("shadow_cost_usd") or 0.0)  # logged, never charged
                if self.provider.live and self.budget is not None:
                    self.budget.count_call(ctx.title_id)
            else:
                cost = self.price.cost(resp.usage.input_tokens, resp.usage.output_tokens) if self.price else 0.0
                if self.provider.live and self.budget is not None:
                    self.budget.charge(cost, ctx.title_id, ctx.episode_id)
            total = total + resp.usage
            substituted = self.provider.live and not same_model(self.spec.model, resp.model)
            kept = {k: resp.meta[k] for k in KEPT_META if k in resp.meta}
            cli_meta = {k: resp.meta[k] for k in ("cli", "cli_version", "init", "other_models") if k in resp.meta}
            if "init" in resp.meta:
                cli_meta["unexpected"] = unexpected_loads(resp.meta["init"], expected_tools=resp.meta.get("expected_tools"))
            cli_meta = {**cli_meta, **kept} or None
            if substituted and self.spec.strict_model:
                self.runlog.log_call(**log_common, model=resp.model, cache_hit=False, attempt=attempt,
                                     input_tokens=resp.usage.input_tokens, output_tokens=resp.usage.output_tokens,
                                 cache_read_tokens=resp.usage.cache_read_tokens,
                                 cache_write_tokens=resp.usage.cache_write_tokens,
                                     cost_usd=cost, user=attempt_user, response=None, meta=cli_meta, timing=timing,
                                     error=f"refused: strict slot answered by {resp.model}, not {self.spec.model}")
                raise ModelSubstituted(f"{self.spec.model} was substituted by {resp.model}; strict slot refuses it")
            self.runlog.log_call(**log_common, model=resp.model, cache_hit=False, attempt=attempt,
                                 input_tokens=resp.usage.input_tokens, output_tokens=resp.usage.output_tokens,
                                 cache_read_tokens=resp.usage.cache_read_tokens,
                                 cache_write_tokens=resp.usage.cache_write_tokens,
                                 cost_usd=cost, user=attempt_user, response=resp.text, meta=cli_meta, timing=timing,
                                 error=f"substituted: served by {resp.model}" if substituted else None)
            try:
                data = parse_json(resp.text)
                run_validate(validate, data, kept)
            except (ValueError, ValidationError) as exc:
                errors.append(str(exc))
                if attempt == 0:
                    attempt_user = user + REPAIR_SUFFIX.format(error=str(exc)[:800])
                    continue
                raise InvalidOutput(errors, resp.text) from exc
            if not substituted:  # a fallback answer is never cached: reruns retry the requested model
                self.cache.put(ctx.pass_, key, {"json": data, "model": resp.model, "usage": asdict(total),
                                                "provider": self.provider_name, "identity": self.identity,
                                                "meta": kept})
            return Completion(data, total, resp.model, key, False, substituted, self.identity, kept)
        raise AssertionError("unreachable")  # pragma: no cover
