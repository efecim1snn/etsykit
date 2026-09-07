"""Bulk listing operations: export current listings, and create/update from a CSV.

Everything is validated locally before a single request goes out. A 400 from Etsy
costs a round trip and tells you very little; a local check tells you the row number
and the exact field. Rows are independent — one bad row does not stop the batch.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .client import EtsyClient
from .config import (
    LISTING_TYPES,
    MAX_MATERIAL_LEN,
    MAX_MATERIALS,
    MAX_TAG_LEN,
    MAX_TAGS,
    MAX_TITLE_LEN,
    WHEN_MADE,
    WHO_MADE,
)
from .csvio import as_bool, as_float, as_int, resolve_paths, split_multi
from .errors import EtsyApiError, ValidationError

# The CSV contract. `listing_id` empty means "create"; filled means "update".
LISTING_COLUMNS = [
    "listing_id",
    "title",
    "description",
    "price",
    "quantity",
    "who_made",
    "when_made",
    "taxonomy_id",
    "type",
    "tags",
    "materials",
    "shipping_profile_id",
    "return_policy_id",
    "shop_section_id",
    "processing_min",
    "processing_max",
    "is_supply",
    "is_customizable",
    "is_taxable",
    "should_auto_renew",
    "item_weight",
    "item_weight_unit",
    "item_length",
    "item_width",
    "item_height",
    "item_dimensions_unit",
    "images",
    "state",
]

# Fields Etsy accepts on PATCH. `quantity` and `price` are deliberately absent:
# on a listing with variations they live in the inventory endpoint, and sending
# them here would silently flatten a seller's variation pricing.
UPDATABLE = {
    "title", "description", "tags", "materials", "taxonomy_id", "who_made", "when_made",
    "shipping_profile_id", "return_policy_id", "shop_section_id", "type", "is_supply",
    "is_taxable", "should_auto_renew", "item_weight", "item_weight_unit", "item_length",
    "item_width", "item_height", "item_dimensions_unit", "state",
}

# Etsy's tag charset: letters, digits, whitespace, and this handful of symbols.
_TAG_EXTRA = set(" -'™©®")

_WEIGHT_UNITS = {"oz", "lb", "g", "kg"}
_DIMENSION_UNITS = {"in", "ft", "mm", "cm", "m", "yd", "inches"}

# Every state a listing can report. Only two of them can be *set* through the API —
# the rest come back from `listings pull` and must round-trip without failing.
LISTING_STATES = {"active", "inactive", "draft", "expired", "sold_out"}
SETTABLE_STATES = {"active", "inactive"}


@dataclass
class RowResult:
    row: int
    action: str = "skip"
    status: str = "ok"
    listing_id: int | None = None
    title: str = ""
    message: str = ""
    images_uploaded: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return self.status == "error"


@dataclass
class PushReport:
    results: list[RowResult] = field(default_factory=list)

    @property
    def created(self) -> int:
        return sum(1 for r in self.results if r.action == "create" and not r.failed)

    @property
    def updated(self) -> int:
        return sum(1 for r in self.results if r.action == "update" and not r.failed)

    @property
    def errors(self) -> int:
        return sum(1 for r in self.results if r.failed)

    @property
    def images(self) -> int:
        return sum(r.images_uploaded for r in self.results)


def bad_tag_chars(tag: str) -> set[str]:
    """Characters Etsy will reject. str.isalnum() is Unicode-aware, so 'çiçek' passes."""
    return {ch for ch in tag if not (ch.isalnum() or ch in _TAG_EXTRA)}


def validate_tags(tags: Sequence[str]) -> list[str]:
    problems = []
    if len(tags) > MAX_TAGS:
        problems.append(f"{len(tags)} tags given, Etsy allows {MAX_TAGS}")
    for tag in tags:
        if len(tag) > MAX_TAG_LEN:
            problems.append(f"tag {tag!r} is {len(tag)} chars, max {MAX_TAG_LEN}")
        bad = bad_tag_chars(tag)
        if bad:
            problems.append(f"tag {tag!r} contains disallowed character(s): {''.join(sorted(bad))}")
    lowered = [t.lower() for t in tags]
    dupes = {t for t in lowered if lowered.count(t) > 1}
    if dupes:
        problems.append(f"duplicate tags: {', '.join(sorted(dupes))}")
    return problems


def build_payload(
    row: dict[str, str], *, is_update: bool, warnings: list[str] | None = None
) -> dict[str, Any]:
    """Turn one CSV row into an Etsy payload, raising ValidationError with a precise reason.

    Non-fatal observations are appended to `warnings` when a list is supplied.
    """
    problems: list[str] = []
    payload: dict[str, Any] = {}

    title = row.get("title", "").strip()
    if title:
        if len(title) > MAX_TITLE_LEN:
            problems.append(f"title is {len(title)} chars, max {MAX_TITLE_LEN}")
        payload["title"] = title
    elif not is_update:
        problems.append("title is required")

    description = row.get("description", "").strip()
    if description:
        payload["description"] = description
    elif not is_update:
        problems.append("description is required")

    listing_type = (row.get("type") or "").strip().lower()
    if listing_type:
        if listing_type not in LISTING_TYPES:
            problems.append(f"type must be one of {', '.join(LISTING_TYPES)}")
        payload["type"] = listing_type
    elif not is_update:
        listing_type = "physical"
        payload["type"] = listing_type

    for name, caster, required in (
        ("price", as_float, not is_update),
        ("quantity", as_int, not is_update),
        ("taxonomy_id", as_int, not is_update),
    ):
        try:
            value = caster(row.get(name, ""), name, required=required)
        except ValidationError as exc:
            problems.append(str(exc))
            continue
        if value is not None:
            payload[name] = value

    for name in ("shipping_profile_id", "return_policy_id", "shop_section_id",
                 "processing_min", "processing_max"):
        try:
            value = as_int(row.get(name, ""), name)
        except ValidationError as exc:
            problems.append(str(exc))
            continue
        if value is not None:
            payload[name] = value

    for name in ("item_weight", "item_length", "item_width", "item_height"):
        try:
            value = as_float(row.get(name, ""), name)
        except ValidationError as exc:
            problems.append(str(exc))
            continue
        if value is not None:
            payload[name] = value

    for name in ("is_supply", "is_customizable", "is_taxable", "should_auto_renew"):
        try:
            value = as_bool(row.get(name, ""), name)
        except ValidationError as exc:
            problems.append(str(exc))
            continue
        if value is not None:
            payload[name] = value

    who = (row.get("who_made") or "").strip().lower()
    if who:
        if who not in WHO_MADE:
            problems.append(f"who_made must be one of {', '.join(WHO_MADE)}")
        payload["who_made"] = who
    elif not is_update:
        problems.append("who_made is required")

    when = (row.get("when_made") or "").strip().lower()
    if when:
        if when not in WHEN_MADE:
            problems.append(f"when_made {when!r} is not a valid Etsy period")
        payload["when_made"] = when
    elif not is_update:
        problems.append("when_made is required")

    weight_unit = (row.get("item_weight_unit") or "").strip().lower()
    if weight_unit:
        if weight_unit not in _WEIGHT_UNITS:
            problems.append(f"item_weight_unit must be one of {', '.join(sorted(_WEIGHT_UNITS))}")
        payload["item_weight_unit"] = weight_unit

    dim_unit = (row.get("item_dimensions_unit") or "").strip().lower()
    if dim_unit:
        if dim_unit not in _DIMENSION_UNITS:
            problems.append(f"item_dimensions_unit must be one of {', '.join(sorted(_DIMENSION_UNITS))}")
        payload["item_dimensions_unit"] = dim_unit

    tags = split_multi(row.get("tags", ""))
    if tags:
        problems.extend(validate_tags(tags))
        payload["tags"] = tags

    materials = split_multi(row.get("materials", ""))
    if materials:
        if len(materials) > MAX_MATERIALS:
            problems.append(f"{len(materials)} materials given, Etsy allows {MAX_MATERIALS}")
        for material in materials:
            if len(material) > MAX_MATERIAL_LEN:
                problems.append(f"material {material!r} exceeds {MAX_MATERIAL_LEN} chars")
        payload["materials"] = materials

    state = (row.get("state") or "").strip().lower()
    if state:
        if state not in LISTING_STATES:
            problems.append(f"state {state!r} is not an Etsy listing state")
        elif state in SETTABLE_STATES:
            if not is_update:
                problems.append("state can only be set when updating an existing listing")
            else:
                payload["state"] = state
        # draft / expired / sold_out are readable but not settable. `listings pull`
        # writes them, so silently ignore them rather than failing a round trip on
        # this tool's own output.

    # etsykit only ever creates drafts, and Etsy does not require a shipping profile
    # on a draft — so this is a warning, not a blocker. A seller who has not built a
    # profile yet can still stage 300 drafts; they just cannot publish them.
    if (
        not is_update
        and payload.get("type", "physical") in {"physical", "both"}
        and "shipping_profile_id" not in payload
        and warnings is not None
    ):
        warnings.append(
            "no shipping_profile_id — fine for a draft, but you cannot publish "
            "without one (see `etsykit shop profiles`)"
        )

    if is_update:
        payload = {k: v for k, v in payload.items() if k in UPDATABLE}
        if not payload:
            problems.append("no updatable fields present in this row")

    if problems:
        raise ValidationError("; ".join(problems))
    return payload


def push(
    client: EtsyClient | None,
    rows: Sequence[dict[str, str]],
    *,
    base_dir: Path,
    dry_run: bool = False,
    upload_images: bool = True,
    on_progress: Callable[[RowResult], None] | None = None,
) -> PushReport:
    """Apply a CSV to the shop. `client` may be None when dry_run is set — validation
    is entirely local, so a seller still waiting on API approval can check their file."""
    if client is None and not dry_run:
        raise ValidationError("A client is required unless dry_run is set.")

    report = PushReport()

    for index, row in enumerate(rows, start=2):  # row 1 is the header
        listing_id = None
        try:
            listing_id = as_int(row.get("listing_id", ""), "listing_id")
        except ValidationError as exc:
            result = RowResult(row=index, status="error", message=str(exc), title=row.get("title", ""))
            report.results.append(result)
            if on_progress:
                on_progress(result)
            continue

        is_update = listing_id is not None
        result = RowResult(
            row=index,
            action="update" if is_update else "create",
            listing_id=listing_id,
            title=row.get("title", "")[:60],
        )

        try:
            payload = build_payload(row, is_update=is_update, warnings=result.warnings)
        except ValidationError as exc:
            result.status = "error"
            result.message = str(exc)
            report.results.append(result)
            if on_progress:
                on_progress(result)
            continue

        image_paths = resolve_paths(split_multi(row.get("images", "")), base_dir)
        missing = [p for p in image_paths if not p.is_file()]
        if missing:
            result.status = "error"
            result.message = f"image not found: {', '.join(str(p) for p in missing[:3])}"
            report.results.append(result)
            if on_progress:
                on_progress(result)
            continue

        if dry_run:
            result.status = "dry-run"
            result.message = f"{len(payload)} fields, {len(image_paths)} image(s)"
            report.results.append(result)
            if on_progress:
                on_progress(result)
            continue

        try:
            if is_update:
                client.update_listing(listing_id, payload)  # type: ignore[arg-type]
            else:
                created = client.create_draft_listing(payload)
                result.listing_id = int(created["listing_id"])
                listing_id = result.listing_id

            if upload_images and image_paths and listing_id:
                for rank, image in enumerate(image_paths, start=1):
                    client.upload_listing_image(listing_id, image, rank=rank)
                    result.images_uploaded += 1

            result.message = "created as draft" if not is_update else "updated"
        except EtsyApiError as exc:
            result.status = "error"
            hint = exc.hint()
            result.message = f"{exc.message}{' — ' + hint if hint else ''}"
        except (OSError, KeyError, ValueError) as exc:
            result.status = "error"
            result.message = str(exc)

        report.results.append(result)
        if on_progress:
            on_progress(result)

    return report


def pull(client: EtsyClient, *, state: str = "active", max_items: int | None = None) -> list[dict[str, Any]]:
    """Export listings into the same CSV shape that `push` consumes."""
    rows = []
    for listing in client.listings_by_shop(state=state, max_items=max_items):
        price = listing.get("price") or {}
        amount = price.get("amount")
        divisor = price.get("divisor") or 100
        rows.append(
            {
                "listing_id": listing.get("listing_id"),
                "title": listing.get("title", ""),
                "description": listing.get("description", ""),
                "price": round(amount / divisor, 2) if isinstance(amount, (int, float)) else "",
                "quantity": listing.get("quantity", ""),
                "who_made": listing.get("who_made", ""),
                "when_made": listing.get("when_made", ""),
                "taxonomy_id": listing.get("taxonomy_id", ""),
                "type": listing.get("listing_type", ""),
                "tags": listing.get("tags") or [],
                "materials": listing.get("materials") or [],
                "shipping_profile_id": listing.get("shipping_profile_id") or "",
                "return_policy_id": listing.get("return_policy_id") or "",
                "shop_section_id": listing.get("shop_section_id") or "",
                "processing_min": listing.get("processing_min") or "",
                "processing_max": listing.get("processing_max") or "",
                "is_supply": listing.get("is_supply"),
                "is_customizable": listing.get("is_customizable"),
                "is_taxable": listing.get("is_taxable"),
                "should_auto_renew": listing.get("should_auto_renew"),
                "item_weight": listing.get("item_weight") or "",
                "item_weight_unit": listing.get("item_weight_unit") or "",
                "item_length": listing.get("item_length") or "",
                "item_width": listing.get("item_width") or "",
                "item_height": listing.get("item_height") or "",
                "item_dimensions_unit": listing.get("item_dimensions_unit") or "",
                "images": "",  # Etsy serves images by URL; re-uploading them is never wanted.
                "state": listing.get("state", ""),
                "url": listing.get("url", ""),
                "views": listing.get("views", ""),
                "num_favorers": listing.get("num_favorers", ""),
            }
        )
    return rows
