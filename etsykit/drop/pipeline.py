"""Folder of designs in, validated listing CSV out.

The pipeline stops at the CSV on purpose. `etsykit listings push` takes it from
there, and that code already has tests behind it — so everything here sits *before*
the tested boundary rather than inside it, and a seller who would rather work in a
spreadsheet can edit the file and get an identical result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .. import csvio
from ..client import EtsyClient
from ..listings import LISTING_COLUMNS
from ..seo import MarketReport, research
from . import cache, generate, mockup, seeds
from .template import Template
from .workspace import Workspace

REVIEW_FILE = "review.csv"

# Columns the review file carries beyond what `listings push` reads. push() ignores
# extras, so the same file serves both the seller's eye and the writer.
REVIEW_EXTRA_COLUMNS = ["source_file", "concept", "evidence", "warnings"]


@dataclass
class DropRow:
    source: Path
    seed: seeds.Seed
    title: str = ""
    tags: list[str] = field(default_factory=list)
    description: str = ""
    images: list[Path] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    skipped: bool = False

    @property
    def ok(self) -> bool:
        return not self.skipped and bool(self.title) and bool(self.images)


@dataclass
class DropReport:
    batch: str
    out_dir: Path
    csv_path: Path | None = None
    rows: list[DropRow] = field(default_factory=list)
    concepts: int = 0
    researched: int = 0
    cached: int = 0

    @property
    def ready(self) -> list[DropRow]:
        return [r for r in self.rows if r.ok]

    @property
    def skipped(self) -> list[DropRow]:
        return [r for r in self.rows if not r.ok]

    @property
    def images_made(self) -> int:
        return sum(len(r.images) for r in self.rows)


def estimate_requests(products: int, concepts: int, images_per_product: int) -> int:
    """What a run will cost against the daily allowance, before it starts.

    A Personal Access app gets 5,000 requests a day. Research pages at 100 listings
    each, then every product costs one create plus one upload per image.
    """
    research_calls = concepts * 2  # a 200-listing sample is two pages of 100
    write_calls = products * (1 + images_per_product)
    return research_calls + write_calls


def _batch_name() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")


def _research_concept(
    client: EtsyClient | None, concept: str, *, sample: int, use_cache: bool
) -> tuple[MarketReport | None, bool]:
    """Returns (report, came_from_cache)."""
    key = f"{concept}|{sample}"
    if use_cache:
        cached = cache.load(key)
        if cached is not None:
            return MarketReport(**cached), True
    if client is None:
        return None, False
    report = research(client, concept, sample=sample)
    if use_cache:
        cache.store(key, report.__dict__)
    return report, False


def run(
    workspace: Workspace,
    template: Template,
    *,
    client: EtsyClient | None = None,
    mockups_per_product: int = 5,
    include_flat: bool = True,
    sample: int = 200,
    use_cache: bool = True,
    on_progress: Callable[[str], None] | None = None,
) -> DropReport:
    """Composite, research, write copy, and emit review.csv. Nothing is sent to Etsy."""
    workspace.require()

    def say(message: str) -> None:
        if on_progress:
            on_progress(message)

    designs = workspace.product_files()
    report = DropReport(batch=_batch_name(), out_dir=workspace.drafts / _batch_name())
    report.out_dir = workspace.drafts / report.batch

    if not designs:
        return report

    mockups = workspace.mockup_files()[:mockups_per_product]
    positions = mockup.load_positions(workspace.positions_path)

    # The folder name is a useful fallback for `2-PRODUCTS/mountain sunset/IMG_01.png`,
    # but never for a file sitting directly in 2-PRODUCTS — that would turn the
    # workspace's own structural folder into a product concept.
    rows = [
        DropRow(
            source=path,
            seed=seeds.derive(path, folder_fallback=path.parent != workspace.products),
        )
        for path in designs
    ]
    grouped = seeds.group([r.seed for r in rows])
    report.concepts = len(grouped)

    # One lookup per distinct concept, not per file. Eighteen concepts across a
    # hundred products is eighteen searches.
    reports: dict[str, MarketReport | None] = {}
    for concept in grouped:
        market, from_cache = _research_concept(client, concept, sample=sample, use_cache=use_cache)
        reports[concept] = market
        if from_cache:
            report.cached += 1
        elif market is not None:
            report.researched += 1
        say(f"researched {concept!r}" + (" (cached)" if from_cache else ""))

    for row in rows:
        if not row.seed:
            row.skipped = True
            row.warnings.append(row.seed.reason or "no concept could be read from the filename")
            say(f"skipped {row.source.name}")
            continue

        copy = generate.generate(
            row.seed,
            reports.get(row.seed.text),
            template_description=template.description,
            fallback_tags=template.tags,
        )
        row.title, row.tags = copy.title, copy.tags
        row.description = copy.description
        row.evidence, row.warnings = copy.sources, list(copy.warnings)

        stem = row.source.stem
        is_artwork = mockup.looks_like_artwork(row.source)

        if not is_artwork:
            # A finished product photo needs no compositing; use it as it is.
            row.images = [row.source]
        else:
            for template_image in mockups:
                area = positions.get(template_image.name, mockup.DEFAULT_PRINT_AREA)
                out = report.out_dir / f"{stem}--{template_image.stem}.jpg"
                try:
                    row.images.append(
                        mockup.compose(row.source, template_image, out, area=area)
                    )
                except Exception as exc:  # noqa: BLE001 — one bad file must not stop a batch
                    row.warnings.append(f"mockup {template_image.name} failed: {exc}")
            if include_flat:
                flat = report.out_dir / f"{stem}--flat.jpg"
                try:
                    row.images.append(mockup.flatten_design(row.source, flat))
                except Exception as exc:  # noqa: BLE001
                    row.warnings.append(f"flat render failed: {exc}")

        if not row.images:
            row.skipped = True
            row.warnings.append(
                "no images produced — put at least one mockup in 1-MOCKUPS, "
                "or drop a finished product photo instead of transparent artwork"
            )
        say(f"prepared {row.source.name}")

    report.rows = rows
    if report.ready:
        report.csv_path = report.out_dir / REVIEW_FILE
        csvio.write_rows(
            report.csv_path,
            [_to_csv_row(r, template, report.csv_path.parent) for r in report.ready],
            columns=LISTING_COLUMNS + REVIEW_EXTRA_COLUMNS,
        )
    return report


def _to_csv_row(row: DropRow, template: Template, base: Path) -> dict[str, Any]:
    """One row in exactly the shape `etsykit listings push` consumes.

    `listing_id` is left empty, always. That is what makes this pipeline structurally
    incapable of updating or publishing an existing listing: Etsy only accepts a state
    change on an update, and there is never an id here to update.
    """
    data: dict[str, Any] = dict(template.fields)
    data.update(
        {
            "listing_id": "",
            "title": row.title,
            "description": row.description,
            "tags": row.tags,
            "materials": template.materials,
            "state": "",
            "images": [_relative(p, base) for p in row.images],
            "source_file": row.source.name,
            "concept": row.seed.text,
            "evidence": "; ".join(row.evidence),
            "warnings": "; ".join(row.warnings),
        }
    )
    return data


def _relative(path: Path, base: Path) -> str:
    """push() resolves image paths against the CSV's own folder."""
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)
