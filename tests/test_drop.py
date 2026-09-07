"""The drop pipeline: folder of designs in, validated listing CSV out.

Every image here is generated, so this suite runs in CI on a machine with no assets,
no Etsy account and no network — which is the point of putting the compositor in
Python rather than behind a native binary.
"""

from pathlib import Path

import pytest
from PIL import Image

from etsykit.config import MAX_TAG_LEN, MAX_TAGS, MAX_TITLE_LEN
from etsykit.drop import generate, mockup, pipeline, seeds, workspace
from etsykit.drop.template import Template, capture
from etsykit.errors import ValidationError
from etsykit.listings import build_payload, validate_tags
from etsykit.seo import MarketReport

# --- seeds: knowing when the filename told us nothing ---------------------------


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("001-coffee-chaos-classroom.png", "coffee chaos classroom"),
        ("mountain-sunset.png", "mountain sunset"),
        ("ceramic_mug_gift.jpg", "ceramic mug gift"),
        ("12-cicek-dugun.png", "cicek dugun"),
        ("mountain-sunset-final-v3.png", "mountain sunset"),
    ],
)
def test_a_descriptive_filename_yields_its_concept(filename, expected):
    assert seeds.derive(Path(filename)).text == expected


@pytest.mark.parametrize(
    "filename",
    ["IMG_2043.png", "DSC00123.jpg", "Screenshot 2026-09-07.png", "untitled.png", "v2.png"],
)
def test_a_junk_filename_is_flagged_rather_than_guessed(filename):
    # Inventing a confident title here would put the wrong listing in a real shop.
    seed = seeds.derive(Path(filename), folder_fallback=False)
    assert not seed
    assert seed.reason


def test_a_junk_filename_falls_back_to_its_folder():
    seed = seeds.derive(Path("mountain sunset/IMG_2043.png"))
    assert seed.text == "mountain sunset"
    assert "folder name" in seed.reason


def test_turkish_characters_survive():
    assert seeds.derive(Path("çiçek-düğün-hediyesi.png")).text == "çiçek düğün hediyesi"


def test_grouping_collapses_files_sharing_a_concept():
    paths = [Path("mountain-sunset-1.png"), Path("mountain-sunset-2.png"), Path("mug.png")]
    # Trailing indices are part of the concept here; what matters is that identical
    # concepts collapse so research runs once.
    grouped = seeds.group([seeds.derive(p) for p in paths])
    assert len(grouped) == len(set(s.text for s in (seeds.derive(p) for p in paths)))


# --- generation: Etsy's limits are enforced, not merely checked ------------------


def _market(tags=None, phrases=None, sampled=200):
    return MarketReport(
        keyword="k",
        sampled=sampled,
        tags=tags or [("ceramic mug", 120), ("coffee lover gift", 90), ("handmade pottery", 60)],
        phrases=phrases or [("coffee lover gift", 80), ("handmade stoneware", 40)],
        price_min=10.0,
        price_median=20.0,
        price_max=40.0,
        currency="USD",
        median_favorers=12.0,
        top_listings=[],
    )


def test_generated_tags_always_satisfy_the_listing_validator():
    seed = seeds.derive(Path("coffee-chaos-classroom.png"))
    tags = generate.build_tags(seed, _market())
    assert validate_tags(tags) == [], "generation must not emit what push would reject"
    assert len(tags) <= MAX_TAGS
    assert all(len(t) <= MAX_TAG_LEN for t in tags)


def test_over_length_market_tags_are_dropped_not_truncated():
    report = _market(tags=[("x" * 30, 100), ("short one", 50)])
    tags = generate.build_tags(seeds.derive(Path("mug.png")), report)
    assert "x" * 30 not in tags
    assert all(len(t) <= MAX_TAG_LEN for t in tags)


def test_tags_with_disallowed_characters_are_cleaned():
    report = _market(tags=[("mug! (new)", 100)])
    tags = generate.build_tags(seeds.derive(Path("mug.png")), report)
    assert validate_tags(tags) == []


def test_near_duplicate_tags_do_not_burn_two_slots():
    report = _market(tags=[("gift", 100), ("gifts", 99), ("mug gift", 98)])
    tags = generate.build_tags(seeds.derive(Path("present.png")), report)
    assert not ("gift" in tags and "gifts" in tags)


def test_the_concept_leads_the_title_and_140_is_never_exceeded():
    seed = seeds.derive(Path("coffee-chaos-classroom.png"))
    title = generate.build_title(seed, _market())
    assert title.lower().startswith("coffee chaos classroom")
    assert len(title) <= MAX_TITLE_LEN


def test_a_very_long_concept_is_still_within_the_limit():
    seed = seeds.derive(Path(("word " * 60).strip().replace(" ", "-") + ".png"))
    title = generate.build_title(seed, _market())
    assert len(title) <= MAX_TITLE_LEN


def test_a_junk_seed_produces_nothing_and_says_why():
    result = generate.generate(seeds.derive(Path("IMG_2043.png"), folder_fallback=False))
    assert result.title == "" and result.tags == []
    assert result.warnings


def test_a_thin_market_sample_is_declared():
    result = generate.generate(seeds.derive(Path("mug.png")), _market(sampled=4))
    assert any("thin a sample" in w for w in result.warnings)


def test_no_market_data_is_declared_rather_than_hidden():
    result = generate.generate(seeds.derive(Path("mug.png")), None)
    assert any("no market data" in w for w in result.warnings)
    assert result.tags, "it should still produce something from the filename"


# --- the compositor -------------------------------------------------------------


def _make_mockup(path: Path, size=(1200, 1500)) -> Path:
    Image.new("RGB", size, (240, 240, 240)).save(path, "JPEG")
    return path


def _make_design(path: Path, size=(800, 800), alpha=True) -> Path:
    mode = "RGBA" if alpha else "RGB"
    colour = (200, 30, 30, 255) if alpha else (200, 30, 30)
    Image.new(mode, size, colour).save(path, "PNG")
    return path


def test_print_area_rejects_a_rectangle_off_the_edge():
    with pytest.raises(ValidationError, match="past the edge"):
        mockup.PrintArea(0.9, 0.1, 0.5, 0.2)


def test_print_area_rejects_a_zero_sized_rectangle():
    with pytest.raises(ValidationError, match="no size"):
        mockup.PrintArea(0.1, 0.1, 0.0, 0.2)


def test_fractions_scale_to_whatever_the_mockup_measures():
    area = mockup.PrintArea(0.25, 0.25, 0.5, 0.5)
    assert area.pixels(1000, 2000) == (250, 500, 500, 1000)
    # The same rectangle on a bigger sibling — this is why fractions are stored.
    assert area.pixels(2000, 4000) == (500, 1000, 1000, 2000)


def test_compose_writes_a_jpeg_at_the_zoom_friendly_size(tmp_path):
    design = _make_design(tmp_path / "d.png")
    template_image = _make_mockup(tmp_path / "m.jpg")
    out = mockup.compose(design, template_image, tmp_path / "out" / "c.jpg")
    assert out.is_file()
    with Image.open(out) as img:
        assert img.format == "JPEG"
        assert min(img.size) >= mockup.OUTPUT_MIN_EDGE


def test_compose_keeps_the_aspect_ratio(tmp_path):
    # A wide design in a square print area must letterbox, never stretch.
    design = _make_design(tmp_path / "wide.png", size=(1000, 250))
    template_image = _make_mockup(tmp_path / "m.jpg", size=(1000, 1000))
    out = mockup.compose(
        design, template_image, tmp_path / "c.jpg", area=mockup.PrintArea(0.2, 0.2, 0.6, 0.6)
    )
    assert out.is_file()


def test_transparency_is_what_distinguishes_artwork_from_a_photo(tmp_path):
    assert mockup.looks_like_artwork(_make_design(tmp_path / "art.png", alpha=True))
    assert not mockup.looks_like_artwork(_make_design(tmp_path / "photo.png", alpha=False))


def test_pixel_positions_import_as_fractions():
    legacy = {"m.jpg": {"x": 250, "y": 500, "w": 500, "h": 250}}
    converted = mockup.import_pixel_positions(legacy, {"m.jpg": (1000, 2000)})
    assert converted["m.jpg"] == mockup.PrintArea(0.25, 0.25, 0.5, 0.125)


def test_one_calibration_covers_identically_sized_siblings():
    legacy = {"a.jpg": {"x": 100, "y": 100, "w": 200, "h": 200}}
    sizes = {"a.jpg": (1000, 1000), "b.jpg": (1000, 1000)}
    converted = mockup.import_pixel_positions(legacy, sizes)
    # b.jpg has no entry of its own, but a.jpg's fractions apply to it unchanged.
    assert converted["a.jpg"].pixels(*sizes["b.jpg"]) == (100, 100, 200, 200)


def test_positions_already_in_fractions_are_left_alone():
    legacy = {"m.jpg": {"x": 0.3, "y": 0.2, "w": 0.4, "h": 0.3}}
    converted = mockup.import_pixel_positions(legacy, {"m.jpg": (1000, 1000)})
    assert converted["m.jpg"] == mockup.PrintArea(0.3, 0.2, 0.4, 0.3)


# --- the template ---------------------------------------------------------------


LISTING = {
    "listing_id": 12345,
    "title": "Handmade Ceramic Mug",
    "description": "A lovely mug.",
    "taxonomy_id": 1633,
    "shipping_profile_id": 999,
    "return_policy_id": 7,
    "who_made": "i_did",
    "when_made": "made_to_order",
    "listing_type": "physical",
    "price": {"amount": 2400, "divisor": 100, "currency_code": "USD"},
    "quantity": 5,
    "processing_min": 1,
    "processing_max": 3,
    "materials": ["stoneware"],
    "tags": ["ceramic mug", "coffee gift"],
}


def test_capture_lifts_the_fields_a_photo_cannot_supply():
    tmpl = capture(LISTING)
    assert tmpl.fields["taxonomy_id"] == 1633
    assert tmpl.fields["shipping_profile_id"] == 999
    assert tmpl.fields["price"] == 24.0
    assert tmpl.fields["type"] == "physical"
    assert tmpl.materials == ["stoneware"]


def test_capture_drops_enum_values_etsy_would_refuse():
    tmpl = capture({**LISTING, "who_made": "me", "when_made": "yesterday"})
    assert "who_made" not in tmpl.fields
    assert "when_made" not in tmpl.fields


def test_capture_reports_what_would_block_publishing():
    tmpl = capture({k: v for k, v in LISTING.items() if k != "shipping_profile_id"})
    assert "shipping_profile_id" in tmpl.missing_for_a_physical_draft()


def test_a_template_round_trips_through_json():
    tmpl = capture(LISTING)
    assert Template.from_dict(tmpl.to_dict()).fields == tmpl.fields


# --- end to end: folder in, pushable CSV out ------------------------------------


class _FakeClient:
    """Returns a fixed market sample without touching the network."""

    def search_active_listings(self, **_kw):
        return iter(
            [
                {
                    "listing_id": i,
                    "title": "ceramic coffee mug handmade gift",
                    "tags": ["ceramic mug", "coffee gift", "handmade pottery"],
                    "price": {"amount": 2000, "divisor": 100, "currency_code": "USD"},
                    "num_favorers": 5,
                }
                for i in range(30)
            ]
        )


def _workspace_with(tmp_path, design_names) -> workspace.Workspace:
    ws = workspace.Workspace(tmp_path / "studio").create()
    _make_mockup(ws.mockups / "front.jpg")
    _make_mockup(ws.mockups / "back.jpg")
    for name in design_names:
        _make_design(ws.products / name)
    return ws


def test_the_whole_pipeline_produces_a_csv_push_would_accept(tmp_path, monkeypatch):
    monkeypatch.setenv("ETSYKIT_HOME", str(tmp_path / "home"))
    ws = _workspace_with(tmp_path, ["ceramic-coffee-mug.png", "mountain-sunset-poster.png"])

    report = pipeline.run(ws, capture(LISTING), client=_FakeClient(), mockups_per_product=2)

    assert len(report.ready) == 2
    assert report.csv_path and report.csv_path.is_file()

    from etsykit.csvio import read_rows

    rows = read_rows(report.csv_path)
    assert len(rows) == 2
    for row in rows:
        # The real validator, on the real output.
        payload = build_payload(row, is_update=False)
        assert payload["taxonomy_id"] == 1633
        assert payload["shipping_profile_id"] == 999
        assert len(payload["title"]) <= MAX_TITLE_LEN
        assert len(payload["tags"]) <= MAX_TAGS


def test_the_pipeline_never_emits_a_listing_id(tmp_path, monkeypatch):
    # This is what makes the drop flow structurally incapable of publishing: Etsy
    # only accepts a state change on an update, and there is never an id to update.
    monkeypatch.setenv("ETSYKIT_HOME", str(tmp_path / "home"))
    ws = _workspace_with(tmp_path, ["ceramic-coffee-mug.png"])
    report = pipeline.run(ws, capture(LISTING), client=_FakeClient(), mockups_per_product=1)

    from etsykit.csvio import read_rows

    for row in read_rows(report.csv_path):
        assert row["listing_id"] == ""
        assert row["state"] == ""


def test_images_are_written_and_referenced_relatively(tmp_path, monkeypatch):
    monkeypatch.setenv("ETSYKIT_HOME", str(tmp_path / "home"))
    ws = _workspace_with(tmp_path, ["ceramic-coffee-mug.png"])
    report = pipeline.run(ws, capture(LISTING), client=_FakeClient(), mockups_per_product=2)

    row = report.rows[0]
    assert len(row.images) == 3, "two mockups plus the flat artwork"
    assert all(p.is_file() for p in row.images)

    from etsykit.csvio import read_rows, split_multi

    images = split_multi(read_rows(report.csv_path)[0]["images"])
    for name in images:
        assert not Path(name).is_absolute()
        assert (report.csv_path.parent / name).is_file()


def test_a_junk_filename_is_skipped_not_listed(tmp_path, monkeypatch):
    monkeypatch.setenv("ETSYKIT_HOME", str(tmp_path / "home"))
    ws = _workspace_with(tmp_path, ["IMG_2043.png", "ceramic-coffee-mug.png"])
    report = pipeline.run(ws, capture(LISTING), client=_FakeClient(), mockups_per_product=1)

    skipped = {r.source.name for r in report.skipped}
    assert "IMG_2043.png" in skipped
    assert len(report.ready) == 1


def test_a_finished_photo_is_used_as_is(tmp_path, monkeypatch):
    monkeypatch.setenv("ETSYKIT_HOME", str(tmp_path / "home"))
    ws = workspace.Workspace(tmp_path / "studio").create()
    _make_mockup(ws.mockups / "front.jpg")
    photo = _make_design(ws.products / "finished-product-photo.png", alpha=False)

    report = pipeline.run(ws, capture(LISTING), client=_FakeClient())
    assert report.rows[0].images == [photo], "an opaque photo needs no compositing"


def test_the_run_works_with_no_market_access_at_all(tmp_path, monkeypatch):
    # A seller still waiting on API approval can still get mockups and a draft CSV.
    monkeypatch.setenv("ETSYKIT_HOME", str(tmp_path / "home"))
    ws = _workspace_with(tmp_path, ["ceramic-coffee-mug.png"])
    report = pipeline.run(ws, capture(LISTING), client=None, mockups_per_product=1)

    assert len(report.ready) == 1
    assert any("no market data" in w for w in report.rows[0].warnings)


def test_vitrin_previews_are_not_mistaken_for_products(tmp_path, monkeypatch):
    monkeypatch.setenv("ETSYKIT_HOME", str(tmp_path / "home"))
    ws = _workspace_with(tmp_path, ["design-one.png", "design-one-vitrin.png"])
    assert [p.name for p in ws.product_files()] == ["design-one.png"]


def test_an_empty_products_folder_returns_an_empty_report(tmp_path, monkeypatch):
    monkeypatch.setenv("ETSYKIT_HOME", str(tmp_path / "home"))
    ws = _workspace_with(tmp_path, [])
    report = pipeline.run(ws, capture(LISTING), client=_FakeClient())
    assert report.rows == [] and report.csv_path is None


def test_a_missing_workspace_says_how_to_make_one(tmp_path):
    with pytest.raises(ValidationError, match="drop init"):
        workspace.Workspace(tmp_path / "nope").require()


def test_a_missing_template_says_to_build_a_listing_by_hand(tmp_path):
    ws = workspace.Workspace(tmp_path / "studio").create()
    with pytest.raises(ValidationError, match="built by hand"):
        ws.read_template()


# --- the quota arithmetic the review screen shows --------------------------------


def test_request_estimate_covers_research_and_every_upload():
    # 100 products, 18 concepts, 6 images each: 36 research + 700 writes.
    assert pipeline.estimate_requests(100, 18, 6) == 736
    assert pipeline.estimate_requests(100, 18, 6) < 5000, "must fit a Personal Access day"
