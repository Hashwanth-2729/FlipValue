"""Device catalogue: canonical models, OEM/name aliases and storage variants.

Matching is exact on (manufacturer, alias) after normalising case and whitespace. Nothing is fuzzy-matched:
an unknown model is reported as unknown, never silently mapped to a similar one.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from flipvalue.db.models import DeviceModel, ModelAlias, ModelVariant

COLUMNS = ("model_id", "manufacturer", "name", "release_date", "storage_gb", "aliases", "catalogue_source")


class CatalogueError(ValueError):
    pass


def normalise(text: str) -> str:
    return " ".join(text.split()).casefold()


@dataclass(frozen=True)
class CatalogueEntry:
    model_id: str
    manufacturer: str
    name: str
    release_date: date | None
    storage_gb: tuple[int, ...]
    aliases: tuple[str, ...]
    catalogue_source: str


def read_catalogue(path: Path) -> list[CatalogueEntry]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise CatalogueError(f"{path}: header must be {','.join(COLUMNS)}")
        entries = []
        for line, raw in enumerate(reader, start=2):
            row = {k: (v or "").strip() for k, v in raw.items()}
            where = f"{path.name}:{line}"
            if not (row["model_id"] and row["manufacturer"] and row["name"] and row["catalogue_source"]):
                raise CatalogueError(f"{where}: model_id, manufacturer, name and catalogue_source are required")
            try:
                storage = tuple(sorted({int(s) for s in row["storage_gb"].split("|") if s}))
                released = date.fromisoformat(row["release_date"]) if row["release_date"] else None
            except ValueError as exc:
                raise CatalogueError(f"{where}: bad storage_gb or release_date") from exc
            if not storage or any(not 1 <= s <= 4096 for s in storage):
                raise CatalogueError(f"{where}: at least one storage_gb value 1-4096 is required")
            aliases = tuple(a.strip() for a in row["aliases"].split("|") if a.strip())
            entries.append(CatalogueEntry(row["model_id"], row["manufacturer"], row["name"], released, storage,
                                          aliases, row["catalogue_source"]))
    return entries


def load_catalogue(session: Session, path: Path) -> int:
    """Insert or update every model in the file. Existing models not in the file are kept."""
    entries = read_catalogue(path)
    seen: dict[tuple[str, str], str] = {}
    for entry in entries:
        maker = normalise(entry.manufacturer)
        for alias in (entry.name, *entry.aliases):
            key = (maker, normalise(alias))
            if seen.setdefault(key, entry.model_id) != entry.model_id:
                raise CatalogueError(f"alias {alias!r} is used by both {seen[key]!r} and {entry.model_id!r}")

    for entry in entries:
        model = session.get(DeviceModel, entry.model_id) or DeviceModel(id=entry.model_id)
        model.manufacturer, model.name = entry.manufacturer, entry.name
        model.release_date, model.catalogue_source = entry.release_date, entry.catalogue_source
        session.add(model)
        session.execute(delete(ModelAlias).where(ModelAlias.model_id == entry.model_id))
        session.execute(delete(ModelVariant).where(ModelVariant.model_id == entry.model_id))
        session.flush()
        maker = normalise(entry.manufacturer)
        session.add(ModelAlias(model_id=entry.model_id, manufacturer_norm=maker, alias=entry.name,
                               alias_norm=normalise(entry.name), kind="name"))
        for alias in entry.aliases:
            if normalise(alias) == normalise(entry.name):
                continue
            session.add(ModelAlias(model_id=entry.model_id, manufacturer_norm=maker, alias=alias,
                                   alias_norm=normalise(alias), kind="oem_code" if "-" in alias else "name"))
        for storage in entry.storage_gb:
            session.add(ModelVariant(model_id=entry.model_id, storage_gb=storage))
    session.flush()
    return len(entries)


def _without_suffix(code: str) -> str | None:
    """'SM-G991B/DS' -> 'SM-G991B': phones report OEM codes with regional/dual-SIM suffixes the catalogue may not
    list. None when there is no suffix."""
    base = code.split("/", 1)[0].strip()
    return base if base and base != code.strip() else None


def find_model(session: Session, manufacturer: str, model: str) -> DeviceModel | None:
    """Exact alias match; failing that, the same code without a '/...' suffix."""
    for candidate in (model, _without_suffix(model)):
        if not candidate:
            continue
        alias = session.scalars(
            select(ModelAlias).where(ModelAlias.manufacturer_norm == normalise(manufacturer),
                                     ModelAlias.alias_norm == normalise(candidate))
        ).first()
        if alias:
            return session.get(DeviceModel, alias.model_id)
    return None


def variants(session: Session, model_id: str) -> list[int]:
    return list(session.scalars(
        select(ModelVariant.storage_gb).where(ModelVariant.model_id == model_id).order_by(ModelVariant.storage_gb)
    ))


def aliases(session: Session, model_id: str) -> list[str]:
    return list(session.scalars(
        select(ModelAlias.alias).where(ModelAlias.model_id == model_id, ModelAlias.kind == "oem_code")
        .order_by(ModelAlias.alias)
    ))


def search(session: Session, query: str = "") -> list[DeviceModel]:
    """Models whose manufacturer, name or any alias contains the query (case-insensitive). A model code with a
    suffix (SM-G991B/DS) that matches nothing is retried without it."""
    models = session.scalars(select(DeviceModel).order_by(DeviceModel.manufacturer, DeviceModel.name)).all()
    q = normalise(query)
    if not q:
        return list(models)
    for candidate in (q, _without_suffix(q)):
        if not candidate:
            continue
        matching_ids = set(session.scalars(
            select(ModelAlias.model_id).where(ModelAlias.alias_norm.contains(candidate, autoescape=True))
        ))
        found = [m for m in models
                 if m.id in matching_ids or candidate in normalise(f"{m.manufacturer} {m.name}")]
        if found:
            return found
    return []
