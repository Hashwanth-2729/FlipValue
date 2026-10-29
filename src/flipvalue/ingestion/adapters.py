"""Source adapters turn a source's raw data into rows for the normaliser.

Each row is a dict with the manual-import columns (see IMPORT_COLUMNS). Adapters for authorised feeds
(e.g. an approved marketplace API) belong here; none exist yet because no feed is authorised (docs/DATA_SOURCES.md).
"""

from __future__ import annotations

import csv
import io
import random
from collections.abc import Iterator
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Protocol

IMPORT_COLUMNS = ("manufacturer", "model", "storage_gb", "region", "currency", "grade", "price", "observed_at",
                  "external_ref")
SYNTHETIC_COLUMNS = ("model_id", "manufacturer", "model", "storage_gb", "region", "currency", "grade",
                     "center_price", "spread_pct", "count")


class AdapterError(ValueError):
    pass


class SourceAdapter(Protocol):
    def rows(self) -> Iterator[tuple[int, dict[str, str]]]:
        """Yield (line number, raw row)."""
        ...


class CsvImportAdapter:
    """Manual import of legitimately obtained data, one CSV per source (columns: IMPORT_COLUMNS)."""

    def __init__(self, text: str) -> None:
        self._text = text

    @classmethod
    def from_path(cls, path: Path) -> CsvImportAdapter:
        return cls(path.read_text(encoding="utf-8-sig"))

    def rows(self) -> Iterator[tuple[int, dict[str, str]]]:
        reader = csv.DictReader(io.StringIO(self._text.lstrip("﻿")))
        if tuple(reader.fieldnames or ()) != IMPORT_COLUMNS:
            raise AdapterError(f"CSV header must be {','.join(IMPORT_COLUMNS)}")
        for line, row in enumerate(reader, start=2):
            yield line, {k: (v or "").strip() for k, v in row.items() if k is not None}


class SyntheticAdapter:
    """Deterministic MOCK observations around hand-set centre prices, dated relative to `reference`.

    The output is fiction by construction; it exists so the website and API can be developed and tested.
    """

    def __init__(self, spec_path: Path, reference: date, window_days: int = 120) -> None:
        self._spec_path = spec_path
        self._reference = reference
        self._window = window_days

    def rows(self) -> Iterator[tuple[int, dict[str, str]]]:
        with self._spec_path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            if tuple(reader.fieldnames or ()) != SYNTHETIC_COLUMNS:
                raise AdapterError(f"synthetic spec header must be {','.join(SYNTHETIC_COLUMNS)}")
            line = 0
            for spec in reader:
                key = "|".join(spec[c] for c in ("model_id", "storage_gb", "region", "grade"))
                rng = random.Random(key)
                center, spread = Decimal(spec["center_price"]), float(spec["spread_pct"]) / 100
                step = Decimal("10") if spec["currency"] == "INR" else Decimal("1")
                for i in range(int(spec["count"])):
                    line += 1
                    price = center * Decimal(str(1 + rng.uniform(-spread, spread)))
                    price = (price / step).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * step
                    observed = self._reference - timedelta(days=rng.randint(0, self._window))
                    yield line, {
                        "manufacturer": spec["manufacturer"], "model": spec["model"],
                        "storage_gb": spec["storage_gb"], "region": spec["region"],
                        "currency": spec["currency"], "grade": spec["grade"], "price": str(price),
                        "observed_at": observed.isoformat(), "external_ref": f"synthetic:{key}:{i}",
                    }
