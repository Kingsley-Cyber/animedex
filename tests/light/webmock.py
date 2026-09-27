"""A mock provider that reports web evidence the way the claude CLI does (URLs and counts, never text)."""

from __future__ import annotations

import dataclasses

from animedex.providers.mock import MockProvider


class WebMock(MockProvider):
    def __init__(self, urls, **kw):
        super().__init__(**kw)
        self.urls, self.params = sorted(urls), []

    def generate(self, system, user, json_schema, params):
        self.params.append(params)
        resp = super().generate(system, user, json_schema, params)
        web = {"searches": 2, "fetches": 2, "queries": ["q0", "q1"], "fetched": self.urls[:1], "found": self.urls,
               "urls": self.urls}
        return dataclasses.replace(resp, meta={"web": web})
