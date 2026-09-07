"""CSV helpers.

Sellers edit these files in Excel, Numbers or Google Sheets, so we read and write
UTF-8 with a BOM — without it Excel on Windows mangles accented characters, which
matters when your titles are in Turkish, German or French.

Multi-value cells (tags, materials, image paths) use '|' rather than ',' so that a
tag containing a comma survives a round trip through a spreadsheet.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from .errors import ValidationError

MULTI_SEP = "|"
ENCODING = "utf-8-sig"


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise ValidationError(f"CSV not found: {path}")
    with path.open("r", encoding=ENCODING, newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValidationError(f"{path} is empty — it needs a header row.")
        rows = []
        for row in reader:
            # Normalise headers and drop the all-blank rows spreadsheets love to append.
            clean = {
                (k or "").strip().lower(): (v or "").strip()
                for k, v in row.items()
                if k is not None
            }
            if any(clean.values()):
                rows.append(clean)
    return rows


def write_rows(path: Path, rows: Sequence[dict[str, Any]], *, columns: Sequence[str] | None = None) -> None:
    if not rows and not columns:
        raise ValidationError("Nothing to write and no columns given.")
    if columns is None:
        seen: list[str] = []
        for row in rows:
            for key in row:
                if key not in seen:
                    seen.append(key)
        columns = seen
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding=ENCODING, newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: _cell(row.get(k)) for k in columns})


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return MULTI_SEP.join(str(v) for v in value)
    return str(value)


def split_multi(value: str) -> list[str]:
    """Split a multi-value cell, tolerating commas for people who typed them anyway."""
    if not value:
        return []
    raw = value.split(MULTI_SEP) if MULTI_SEP in value else value.split(",")
    return [part.strip() for part in raw if part.strip()]


def as_int(
    value: str, field: str, *, required: bool = False, minimum: int | None = None
) -> int | None:
    """Parse a whole number.

    A fractional value is an error, not something to round. `quantity=3.9` used to
    become 3 silently, which is a stock level the seller never typed.
    """
    if not value:
        if required:
            raise ValidationError(f"{field} is required")
        return None
    try:
        number = float(value)
    except ValueError as exc:
        raise ValidationError(f"{field} must be a whole number, got {value!r}") from exc
    if number != int(number):
        raise ValidationError(f"{field} must be a whole number, got {value!r}")
    result = int(number)
    if minimum is not None and result < minimum:
        raise ValidationError(f"{field} must be {minimum} or more, got {result}")
    return result


def as_float(
    value: str, field: str, *, required: bool = False, minimum: float | None = None
) -> float | None:
    if not value:
        if required:
            raise ValidationError(f"{field} is required")
        return None
    # Accept '19,90' from locales that use a decimal comma.
    try:
        number = float(
            value.replace(",", ".") if value.count(",") == 1 and "." not in value else value
        )
    except ValueError as exc:
        raise ValidationError(f"{field} must be a number, got {value!r}") from exc
    if minimum is not None and number < minimum:
        raise ValidationError(f"{field} must be {minimum} or more, got {number}")
    return number


def as_bool(value: str, field: str) -> bool | None:
    if not value:
        return None
    lowered = value.strip().lower()
    if lowered in {"1", "true", "yes", "y", "evet", "e"}:
        return True
    if lowered in {"0", "false", "no", "n", "hayir", "hayır", "h"}:
        return False
    raise ValidationError(f"{field} must be true/false, got {value!r}")


def resolve_paths(values: Iterable[str], base: Path) -> list[Path]:
    """Image paths in a CSV are relative to the CSV itself, which is what users expect."""
    out = []
    for value in values:
        candidate = Path(value).expanduser()
        out.append(candidate if candidate.is_absolute() else (base / candidate))
    return out
