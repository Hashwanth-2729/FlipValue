"""Product identity: decide whether a marketplace listing is the catalogue model and storage variant asked for.

Categories (the primary price comparison uses only `exact` and `strong`):
* exact            - an OEM model code from the catalogue appears in the title, and the storage matches
* strong           - brand and model name match as a whole phrase with no variant word after it ("Pro", "FE",
                     "Ultra", ...), and the storage matches (or the model has only one storage variant)
* variant_unknown  - same model, but the listing does not state storage and the model has several variants
* variant_mismatch - same model, different storage
* similar          - same brand, different model (e.g. "Galaxy S21 FE" for "Galaxy S21")
* unmatched        - anything else (not stored)

A textual match is evidence, not proof: every decision keeps its reasons and score so it can be inspected.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from flipvalue import catalogue
from flipvalue.db.models import DeviceModel, ModelAlias

PRIMARY = ("exact", "strong")
CATEGORIES = ("exact", "strong", "variant_unknown", "variant_mismatch", "similar", "unmatched")
# Words that, directly after a model name, make it a different model.
VARIANT_WORDS = {"pro", "plus", "ultra", "max", "mini", "lite", "fe", "edge", "fold", "flip", "neo", "prime", "xl",
                 "se", "note", "a", "s"}
_STORAGE = re.compile(r"(\d{2,4})\s*(gb|tb)\b(?!\s*ram)", re.I)
_RAM = re.compile(r"(\d{1,2})\s*gb\s*ram\b", re.I)


def tokens(text: str) -> list[str]:
    text = text.casefold().replace("+", " plus ")
    return re.findall(r"[a-z0-9]+(?:-[a-z0-9/]+)*", text)


def storage_from_title(title: str) -> int | None:
    """The storage stated in a title, when exactly one size is stated."""
    sizes = {int(n) * (1024 if unit.casefold() == "tb" else 1) for n, unit in _STORAGE.findall(title)}
    return sizes.pop() if len(sizes) == 1 else None


def ram_from_title(title: str) -> int | None:
    found = {int(n) for n in _RAM.findall(title)}
    return found.pop() if len(found) == 1 else None


def _positions(haystack: list[str], phrase: list[str]) -> list[int]:
    n = len(phrase)
    return [i for i in range(len(haystack) - n + 1) if n and haystack[i:i + n] == phrase]


@dataclass
class Match:
    model_id: str | None
    category: str
    score: int
    reasons: list[str] = field(default_factory=list)
    storage_gb: int | None = None  # the listing's storage, stated or implied by a single-variant model

    @property
    def primary(self) -> bool:
        return self.category in PRIMARY


def _identify(session: Session, model: DeviceModel, title_tokens: list[str], brand: str | None) -> Match | None:
    """Brand + model identity, ignoring storage. None if the brand differs."""
    maker = catalogue.normalise(model.manufacturer)
    if not ((brand and catalogue.normalise(brand) == maker) or maker in title_tokens):
        return None
    reasons = [f"brand {model.manufacturer}"]
    aliases = session.execute(select(ModelAlias.alias, ModelAlias.kind).where(ModelAlias.model_id == model.id)).all()
    code = next((a for a, kind in aliases if kind == "oem_code" and _positions(title_tokens, tokens(a))), None)
    if code:
        return Match(model.id, "exact", 100, [*reasons, f"model code {code} in title"])
    variant_word = None
    for alias, kind in aliases:
        if kind != "name":
            continue
        phrase = tokens(alias)
        for pos in _positions(title_tokens, phrase):
            end = pos + len(phrase)
            following = title_tokens[end] if end < len(title_tokens) else None
            if following not in VARIANT_WORDS:
                return Match(model.id, "strong", 85, [*reasons, f"model name '{alias}' appears as a whole phrase"])
            variant_word = variant_word or following
    if variant_word:
        return Match(None, "similar", 30,
                     [*reasons, f"a different model: '{variant_word}' follows the name {model.name}"])
    return Match(None, "similar", 20, [*reasons, f"model name {model.name} not in title"])


def match_listing(session: Session, title: str, brand: str | None, stated_storage: int | None,
                  target: DeviceModel | None = None, wanted_storage: int | None = None) -> Match:
    """Match a listing against `target` (a search for a known model) or, without a target, the whole catalogue.

    `wanted_storage` None accepts any catalogued storage variant of the model.
    """
    title_tokens = tokens(title)
    listed = stated_storage if stated_storage is not None else storage_from_title(title)
    models = [target] if target is not None else list(session.scalars(select(DeviceModel)))
    best = Match(None, "unmatched", 0, ["no catalogue model matches the brand and title"])
    for model in models:
        found = _identify(session, model, title_tokens, brand)
        if found is None:
            continue
        if found.model_id is not None:
            found = _with_storage(model, found, listed, wanted_storage, catalogue.variants(session, model.id))
        if found.score > best.score:
            best = found
    return best


def _with_storage(model: DeviceModel, found: Match, listed: int | None, wanted: int | None,
                  variants: list[int]) -> Match:
    reasons = found.reasons
    if listed is None:
        if len(variants) == 1 and wanted in (None, variants[0]):
            return Match(model.id, found.category, found.score - 10,
                         [*reasons, f"storage not stated; {model.name} only exists with {variants[0]} GB"],
                         variants[0])
        return Match(model.id, "variant_unknown", 50, [*reasons, "storage not stated in the listing"])
    if listed not in variants:
        return Match(model.id, "variant_mismatch", 40,
                     [*reasons, f"{listed} GB is not a catalogued variant of {model.name}"], listed)
    if wanted is not None and listed != wanted:
        return Match(model.id, "variant_mismatch", 45, [*reasons, f"listing is {listed} GB, not {wanted} GB"],
                     listed)
    return Match(model.id, found.category, found.score, [*reasons, f"storage {listed} GB"], listed)
