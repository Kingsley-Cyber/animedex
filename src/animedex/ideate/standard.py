"""One taste standard for every arm of the blind review (controls A5, M5 ruling item 7).

`prompts/taste_standard.md` holds T1-T5 and the hard fail. The generate prompt (ANIMEDEX and
baseline 1) and the single-call baseline (baseline 2) include it through `{taste_standard}`, so every
arm reads the same words. The rendered system prompt's version carries a hash of the full text, so
editing the standard invalidates every cached answer that used it.
"""

from __future__ import annotations

from animedex.paths import Paths
from animedex.prompts import RenderedPrompt, read_prompt

STANDARD_FILE = "taste_standard.md"
SLOT = "{taste_standard}"


def taste_standard(paths: Paths) -> str:
    return read_prompt(paths.prompts / STANDARD_FILE).body.strip()


def render_prompt(paths: Paths, file: str, **values: object) -> RenderedPrompt:
    """`file` with the shared standard in its `{taste_standard}` slot and `{name}` values filled."""
    main = read_prompt(paths.prompts / file)
    body = main.body.replace(SLOT, taste_standard(paths)) if SLOT in main.body else main.body
    for name, value in values.items():
        body = body.replace("{" + name + "}", str(value))
    return RenderedPrompt(body, main.version)
