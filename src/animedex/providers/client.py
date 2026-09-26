"""LLMClient: the one path every pass uses to call a model.

complete(system, user, json_schema, params) -> (json, usage)   (03 provider interface)

Order of operations:
1. cache lookup (key per 05); a hit spends nothing;
2. live calls only: title guard (corpus scope + gold blind guard), then budget check;
3. provider call; JSON parse + validation; on failure, ONE repair call with the error (11),
   then InvalidOutput (the stage quarantines);
4. every attempt is logged with fetched web text redacted, and charged to the budget.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from pydantic import ValidationError

from animedex.budget import Budget, Price
from animedex.config import ModelSpec
from animedex.providers.base import Provider, ProviderError, Usage
from animedex.store.cache import ResponseCache, cache_key
from animedex.store.runlog import RunLog, TransientText

REPAIR_SUFFIX = (
    "\n\nYour previous reply was rejected: {error}\n"
    "Return one corrected JSON object only, matching the schema."
)
_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


class ClientConfigError(RuntimeError):
    pass


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


@dataclass(frozen=True)
class Completion:
    data: dict[str, Any]
    usage: Usage
    model: str
    cache_key: str
    cache_hit: bool


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
    ):
        if provider.live and (price is None or budget is None or title_guard is None):
            raise ClientConfigError(
                f"live provider {provider_name}/{spec.model} needs pricing, budget caps, and the title guard"
            )
        self.provider = provider
        self.provider_name = provider_name
        self.spec = spec
        self.prompt_version = prompt_version
        self.schema_version = schema_version
        self.vocab_version = vocab_version
        self.cache = cache
        self.runlog = runlog
        self.price = price
        self.budget = budget
        self.title_guard = title_guard

    def key_for(self, ctx: CallContext, params: dict[str, Any] | None = None) -> str:
        merged = {**self.spec.params, **(params or {})}
        return cache_key(
            record_id=ctx.record_id,
            pass_=ctx.pass_,
            prompt_version=self.prompt_version,
            schema_version=self.schema_version,
            vocab_version=self.vocab_version,
            model=f"{self.provider_name}/{self.spec.model}",
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

    def complete_ex(
        self,
        system: str,
        user: str,
        json_schema: dict[str, Any],
        params: dict[str, Any] | None = None,
        *,
        ctx: CallContext,
        validate: Callable[[dict[str, Any]], Any] | None = None,
    ) -> Completion:
        key = self.key_for(ctx, params)
        log_common = {"pass_": ctx.pass_, "record_id": ctx.record_id, "provider": self.provider_name,
                      "cache_key": key, "system": system, "transients": ctx.transients}

        hit = self.cache.get(ctx.pass_, key)
        if hit is not None:
            self.runlog.log_call(**log_common, model=hit.get("model", ""), cache_hit=True, attempt=0,
                                 input_tokens=0, output_tokens=0, cost_usd=0.0, user=user,
                                 response=json.dumps(hit["json"], sort_keys=True))
            return Completion(hit["json"], Usage(), hit.get("model", ""), key, True)

        if self.provider.live:
            if ctx.title_id:
                self.title_guard(ctx.title_id)  # type: ignore[misc]
            self.budget.check(ctx.title_id, ctx.episode_id)  # type: ignore[union-attr]

        call_params = {**self.spec.params, **(params or {}), "model": self.spec.model}
        total = Usage()
        errors: list[str] = []
        attempt_user = user
        for attempt in (0, 1):
            sent = dict(call_params)
            if not self.provider.live:
                sent["_meta"] = {"pass": ctx.pass_, "record_id": ctx.record_id, "attempt": attempt}
            try:
                resp = self.provider.generate(system, attempt_user, json_schema, sent)
            except ProviderError as exc:
                self.runlog.log_call(**log_common, model=self.spec.model, cache_hit=False, attempt=attempt,
                                     input_tokens=0, output_tokens=0, cost_usd=0.0, user=attempt_user,
                                     response=None, error=str(exc))
                raise
            cost = self.price.cost(resp.usage.input_tokens, resp.usage.output_tokens) if self.price else 0.0
            if self.provider.live and self.budget is not None:
                self.budget.charge(cost, ctx.title_id, ctx.episode_id)
            total = total + resp.usage
            self.runlog.log_call(**log_common, model=resp.model, cache_hit=False, attempt=attempt,
                                 input_tokens=resp.usage.input_tokens, output_tokens=resp.usage.output_tokens,
                                 cost_usd=cost, user=attempt_user, response=resp.text)
            try:
                data = parse_json(resp.text)
                if validate is not None:
                    validate(data)
            except (ValueError, ValidationError) as exc:
                errors.append(str(exc))
                if attempt == 0:
                    attempt_user = user + REPAIR_SUFFIX.format(error=str(exc)[:800])
                    continue
                raise InvalidOutput(errors, resp.text) from exc
            self.cache.put(ctx.pass_, key, {"json": data, "model": resp.model, "usage": asdict(total),
                                            "provider": self.provider_name})
            return Completion(data, total, resp.model, key, False)
        raise AssertionError("unreachable")  # pragma: no cover
