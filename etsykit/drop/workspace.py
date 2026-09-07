"""The desktop folder that is the whole user interface for input.

Explorer is already the best drag-and-drop target that will ever exist on this
machine — multi-select, thumbnails, rename in place, works over OneDrive and Remote
Desktop — and it costs nothing to use. So the input surface is a folder, and the
folder names itself in the order you use it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..errors import ValidationError

MOCKUPS_DIR = "1-MOCKUPS"
PRODUCTS_DIR = "2-PRODUCTS"
DRAFTS_DIR = "3-DRAFTS"
ARCHIVE_DIR = "archive"

TEMPLATE_FILE = "product.json"
POSITIONS_FILE = "positions.json"

# Design files Pillow can open without an extra. HEIC is deliberately absent: it
# needs pillow-heif, and a missing-extra message beats a decode traceback.
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}

README_TEXT = """\
ETSY STUDIO
===========

1-MOCKUPS   Put your mockup templates here (photos of a blank shirt, mug, poster).
            You only do this once.

2-PRODUCTS  Put the designs you want listed here. This is the folder you use every
            time. One design = one listing.

3-DRAFTS    What comes out. Composited images and review.csv — check it before
            anything is sent to Etsy.

archive/    Designs that have already been listed are moved here, so 2-PRODUCTS
            always shows only what is still waiting.

Nothing here is ever published. Listings are created as DRAFTS in your Etsy shop
and stay invisible to buyers until you publish them yourself.

--------------------------------------------------------------------------------

ETSY STUDIO (TR)
================

1-MOCKUPS   Mockup sablonlarini buraya koy (bos tisort, kupa, poster fotograflari).
            Bunu sadece bir kez yaparsin.

2-PRODUCTS  Listelemek istedigin tasarimlari buraya koy. Her seferinde
            kullanacagin klasor bu. Bir tasarim = bir listing.

3-DRAFTS    Cikan sonuc. Giydirilmis gorseller ve review.csv — Etsy'ye bir sey
            gitmeden once buna bak.

archive/    Listelenmis tasarimlar buraya tasinir, boylece 2-PRODUCTS'ta hep
            sadece bekleyenler kalir.

Hicbir sey yayinlanmaz. Listingler Etsy magazanda TASLAK olarak olusturulur ve sen
kendin yayinlayana kadar alicilar goremez.
"""


@dataclass
class Workspace:
    root: Path

    @property
    def mockups(self) -> Path:
        return self.root / MOCKUPS_DIR

    @property
    def products(self) -> Path:
        return self.root / PRODUCTS_DIR

    @property
    def drafts(self) -> Path:
        return self.root / DRAFTS_DIR

    @property
    def archive(self) -> Path:
        return self.root / ARCHIVE_DIR

    @property
    def template_path(self) -> Path:
        return self.root / TEMPLATE_FILE

    @property
    def positions_path(self) -> Path:
        return self.mockups / POSITIONS_FILE

    def create(self) -> Workspace:
        for path in (self.mockups, self.products, self.drafts, self.archive):
            path.mkdir(parents=True, exist_ok=True)
        readme = self.root / "README.txt"
        if not readme.exists():
            readme.write_text(README_TEXT, encoding="utf-8")
        return self

    def require(self) -> Workspace:
        if not self.root.is_dir():
            raise ValidationError(
                f"No workspace at {self.root}. Create one with: etsykit drop init"
            )
        missing = [d.name for d in (self.mockups, self.products) if not d.is_dir()]
        if missing:
            raise ValidationError(
                f"{self.root} is missing {', '.join(missing)}. "
                "Re-run `etsykit drop init` to repair it."
            )
        return self

    # --- contents ---------------------------------------------------------------

    def mockup_files(self) -> list[Path]:
        return _images(self.mockups)

    def product_files(self, *, exclude_suffixes: tuple[str, ...] = ("-vitrin",)) -> list[Path]:
        """Designs waiting to be listed.

        `-vitrin` files are 1000x1000 showcase renders that sit beside the real
        4500x5400 artwork in this seller's output. Listing them would publish a
        preview as though it were the product.
        """
        files = _images(self.products)
        return [f for f in files if not any(f.stem.endswith(s) for s in exclude_suffixes)]

    def read_template(self) -> dict[str, Any]:
        if not self.template_path.exists():
            raise ValidationError(
                "No product template yet. Point at a listing you built by hand:\n"
                "  etsykit drop template --from-listing <listing_id>\n"
                "If your shop is empty, create one listing properly in Etsy first — "
                "every draft copies its settings."
            )
        try:
            return json.loads(self.template_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValidationError(f"{self.template_path} is not valid JSON: {exc}") from exc

    def write_template(self, data: dict[str, Any]) -> None:
        self.template_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )


def _images(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(
        (p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES),
        key=lambda p: p.name.lower(),
    )


def default_root() -> Path:
    """Desktop if there is one, home otherwise. Never guesses a localised name."""
    desktop = Path.home() / "Desktop"
    base = desktop if desktop.is_dir() else Path.home()
    return base / "Etsy Studio"
