import json

import pytest
from PIL import Image
from typer.testing import CliRunner

from etsykit.cli import app
from etsykit.drop import automation, pipeline
from etsykit.drop.template import Template
from etsykit.drop.workspace import Workspace
from etsykit.errors import ValidationError


@pytest.fixture
def studio(tmp_path):
    ws = Workspace(tmp_path / "studio").create()
    folder = ws.products / "mountain sunset shirt"
    folder.mkdir()
    for name in ("10-detail.png", "2-back.png", "1-front.png"):
        Image.new("RGBA", (20, 20), (20, 30, 40, 100)).save(folder / name)
    template = Template(1, fields={"taxonomy_id": 1, "price": 20, "quantity": 5,
                                    "who_made": "i_did", "when_made": "made_to_order",
                                    "type": "physical"}, description="Cotton shirt.")
    ws.write_template(template.to_dict())
    return ws, template


class Client:
    def __init__(self, ws, fail=None):
        self.ws, self.fail = ws, fail
        self.creates = 0
        self.images = []

    def shop_id(self):
        return 123

    def search_active_listings(self, **kwargs):
        return iter([])

    def create_draft_listing(self, fields):
        self.creates += 1
        state = json.loads((self.ws.root / "upload-history.json").read_text())
        assert state["123"]["mountain sunset shirt"]["status"] == "pending"
        if self.fail == "create":
            raise OSError("response lost")
        return {"listing_id": 900}

    def upload_listing_image(self, listing_id, image, *, rank):
        state = json.loads((self.ws.root / "upload-history.json").read_text())
        assert state["123"]["mountain sunset shirt"]["listing_id"] == 900
        if self.fail == "image":
            raise OSError("upload interrupted")
        self.images.append((image.name, rank))
        return {}


def test_folder_is_one_listing_and_ready_pngs_are_not_composited(studio):
    ws, template = studio
    report = pipeline.run(ws, template)
    assert len(report.ready) == 1
    row = report.ready[0]
    assert row.seed.text == "mountain sunset shirt"
    assert [p.name for p in row.images] == ["1-front.png", "2-back.png", "10-detail.png"]
    assert all(p.parent == row.source for p in row.images)


def test_auto_uploads_all_images_and_second_run_does_not_duplicate(studio):
    ws, template = studio
    client = Client(ws)
    first = automation.run(ws, template, client=client)
    assert first.uploaded.created == 1
    assert client.images == [("1-front.png", 1), ("2-back.png", 2), ("10-detail.png", 3)]
    second = automation.run(ws, template, client=client)
    assert client.creates == 1
    assert second.already_done == ["mountain sunset shirt"]


@pytest.mark.parametrize("failure", ["create", "image"])
def test_uncertain_or_partial_upload_is_not_recreated(studio, failure):
    ws, template = studio
    client = Client(ws, failure)
    automation.run(ws, template, client=client)
    second = automation.run(ws, template, client=client)
    assert client.creates == 1
    assert second.needs_review


def test_cli_dry_run_is_offline_and_does_not_mark_uploaded(studio):
    ws, _ = studio
    result = CliRunner().invoke(app, ["drop", "auto", "--path", str(ws.root), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "validated" in result.output
    assert not (ws.root / "upload-history.json").exists()


def test_corrupt_image_aborts_before_any_upload(studio):
    ws, template = studio
    (ws.products / "mountain sunset shirt" / "2-back.png").write_text("broken")
    client = Client(ws)
    with pytest.raises(ValidationError, match="Invalid image"):
        automation.run(ws, template, client=client)
    assert client.creates == 0


def test_image_overflow_does_not_silently_drop_photos(studio):
    ws, template = studio
    for n in range(11):
        Image.new("RGB", (20, 20)).save(ws.products / "mountain sunset shirt" / f"extra-{n}.jpg")
    client = Client(ws)
    with pytest.raises(ValidationError, match="more than 10"):
        automation.run(ws, template, client=client)
    assert client.creates == 0


def test_lock_and_corrupt_history_block_writes(studio):
    ws, template = studio
    client = Client(ws)
    lock = ws.root / ".auto-upload.lock"
    lock.write_text("another process")
    with pytest.raises(ValidationError, match="Another auto run"):
        automation.run(ws, template, client=client)
    lock.unlink()
    (ws.root / "upload-history.json").write_text("broken")
    with pytest.raises(ValidationError, match="Cannot read"):
        automation.run(ws, template, client=client)
    assert client.creates == 0


def test_invalid_template_aborts_whole_batch(studio):
    ws, template = studio
    template.fields["price"] = -1
    client = Client(ws)
    with pytest.raises(ValidationError, match="Nothing uploaded"):
        automation.run(ws, template, client=client)
    assert client.creates == 0


def test_digital_template_is_not_uploaded_without_delivery_files(studio):
    ws, template = studio
    template.fields["type"] = "download"
    with pytest.raises(ValidationError, match="digital delivery"):
        automation.run(ws, template, dry_run=True)
