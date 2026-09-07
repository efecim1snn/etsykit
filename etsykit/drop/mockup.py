"""Compositing a design onto a mockup template with Pillow.

Print areas are stored as **fractions** of the mockup, not pixels. That one choice
buys three things: a sensible default works before anyone calibrates anything, one
calibrated rectangle covers every sibling mockup of the same dimensions, and the
compositor can be tested in CI on generated images with no assets in the repo.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from ..errors import ValidationError

# A chest print on a folded garment shot, as fractions of the mockup. Deliberately
# conservative: too small reads as a design choice, too large reads as a bug.
DEFAULT_AREA = (0.30, 0.26, 0.40, 0.36)

# Etsy recommends the shortest side be at least 2000px so the zoom viewer works.
OUTPUT_MIN_EDGE = 2000
JPEG_QUALITY = 92


@dataclass(frozen=True)
class PrintArea:
    """Where the design goes, as fractions of the mockup's width and height."""

    x: float
    y: float
    w: float
    h: float

    def __post_init__(self) -> None:
        for name, value in (("x", self.x), ("y", self.y), ("w", self.w), ("h", self.h)):
            if not 0.0 <= value <= 1.0:
                raise ValidationError(f"print area {name}={value} must be between 0 and 1")
        if self.x + self.w > 1.0001 or self.y + self.h > 1.0001:
            raise ValidationError("print area extends past the edge of the mockup")
        if self.w <= 0 or self.h <= 0:
            raise ValidationError("print area has no size")

    def pixels(self, width: int, height: int) -> tuple[int, int, int, int]:
        return (
            round(self.x * width),
            round(self.y * height),
            max(1, round(self.w * width)),
            max(1, round(self.h * height)),
        )

    def to_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}


DEFAULT_PRINT_AREA = PrintArea(*DEFAULT_AREA)


def load_positions(path: Path) -> dict[str, PrintArea]:
    """Read positions.json. A missing file is normal — defaults cover it."""
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValidationError(f"{path} is not valid JSON: {exc}") from exc
    out: dict[str, PrintArea] = {}
    for name, value in (raw or {}).items():
        if not isinstance(value, dict):
            continue
        try:
            out[name] = PrintArea(
                float(value["x"]), float(value["y"]), float(value["w"]), float(value["h"])
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError(f"{path}: entry {name!r} is malformed ({exc})") from exc
    return out


def save_positions(path: Path, positions: dict[str, PrintArea]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {name: area.to_dict() for name, area in sorted(positions.items())}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def import_pixel_positions(
    legacy: dict[str, Any], mockups: dict[str, tuple[int, int]]
) -> dict[str, PrintArea]:
    """Convert an older pixel-based mockup-positions.json into fractions.

    Pixel rectangles only describe the one file they were measured on. Converting to
    fractions makes a single calibration cover every sibling mockup of the same
    dimensions, which is usually most of a set.
    """
    out: dict[str, PrintArea] = {}
    for name, value in (legacy or {}).items():
        if not isinstance(value, dict) or name not in mockups:
            continue
        width, height = mockups[name]
        if not width or not height:
            continue
        try:
            x = float(value.get("x", value.get("left", 0)))
            y = float(value.get("y", value.get("top", 0)))
            w = float(value.get("w", value.get("width", 0)))
            h = float(value.get("h", value.get("height", 0)))
        except (TypeError, ValueError):
            continue
        if w <= 0 or h <= 0:
            continue
        # Values already in 0..1 were fractions to begin with.
        if max(x + w, y + h) <= 1.0:
            out[name] = PrintArea(x, y, w, h)
        else:
            out[name] = PrintArea(x / width, y / height, w / width, h / height)
    return out


def mockup_sizes(paths: list[Path]) -> dict[str, tuple[int, int]]:
    sizes: dict[str, tuple[int, int]] = {}
    for path in paths:
        try:
            with Image.open(path) as img:
                sizes[path.name] = img.size
        except OSError:
            continue
    return sizes


def compose(
    design_path: Path,
    mockup_path: Path,
    out_path: Path,
    *,
    area: PrintArea | None = None,
    min_edge: int = OUTPUT_MIN_EDGE,
) -> Path:
    """Place one design inside one mockup's print area and write a JPEG.

    The design keeps its aspect ratio and is centred in the rectangle, so a square
    print area and a wide design produce letterboxing rather than distortion.
    """
    area = area or DEFAULT_PRINT_AREA
    try:
        with Image.open(mockup_path) as raw_mockup:
            mockup = raw_mockup.convert("RGB")
    except OSError as exc:
        raise ValidationError(f"Cannot open mockup {mockup_path.name}: {exc}") from exc

    try:
        with Image.open(design_path) as raw_design:
            design = raw_design.convert("RGBA")
    except OSError as exc:
        raise ValidationError(
            f"Cannot open design {design_path.name}: {exc}. "
            "If this is an iPhone HEIC photo, install the extra: pip install etsykit[heic]"
        ) from exc

    box_x, box_y, box_w, box_h = area.pixels(*mockup.size)
    scale = min(box_w / design.width, box_h / design.height)
    new_size = (max(1, round(design.width * scale)), max(1, round(design.height * scale)))
    design = design.resize(new_size, Image.LANCZOS)

    offset = (box_x + (box_w - new_size[0]) // 2, box_y + (box_h - new_size[1]) // 2)
    mockup.paste(design, offset, design)

    if min_edge and min(mockup.size) < min_edge:
        factor = min_edge / min(mockup.size)
        mockup = mockup.resize(
            (round(mockup.width * factor), round(mockup.height * factor)), Image.LANCZOS
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    mockup.save(out_path, "JPEG", quality=JPEG_QUALITY, optimize=True)
    return out_path


def flatten_design(design_path: Path, out_path: Path, *, edge: int = OUTPUT_MIN_EDGE) -> Path:
    """Render the artwork itself on white — the image print-on-demand buyers look for.

    Transparent artwork on Etsy's white page is invisible, so it gets a background.
    """
    try:
        with Image.open(design_path) as raw:
            design = raw.convert("RGBA")
    except OSError as exc:
        raise ValidationError(f"Cannot open design {design_path.name}: {exc}") from exc

    canvas = Image.new("RGB", (edge, edge), (255, 255, 255))
    scale = min(edge * 0.86 / design.width, edge * 0.86 / design.height)
    size = (max(1, round(design.width * scale)), max(1, round(design.height * scale)))
    design = design.resize(size, Image.LANCZOS)
    canvas.paste(design, ((edge - size[0]) // 2, (edge - size[1]) // 2), design)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, "JPEG", quality=JPEG_QUALITY, optimize=True)
    return out_path


def looks_like_artwork(path: Path) -> bool:
    """Artwork needs compositing; a finished product photo does not.

    Transparency is the signal that actually means something: a photograph has none,
    and a print file almost always does. Everything else is guesswork, so when there
    is no alpha channel we treat it as a finished photo and let the seller override.
    """
    try:
        with Image.open(path) as img:
            if img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info:
                return True
            return False
    except OSError:
        return False
