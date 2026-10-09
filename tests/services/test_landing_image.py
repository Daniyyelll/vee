"""Landing image validation and persistence behavior."""

import asyncio
from io import BytesIO

import pytest
from PIL import Image

from app.core.exceptions import APIException
from app.services.landing_image import _encode_variants, update_landing_image


def test_upload_is_resized_to_webp_and_strips_metadata():
    source = Image.new("RGB", (1600, 2000), "#c48e72")
    buffer = BytesIO()
    source.save(buffer, "JPEG", exif=b"private-camera-metadata")

    large, small = _encode_variants(buffer.getvalue())

    with Image.open(BytesIO(large)) as image:
        assert image.format == "WEBP"
        assert image.size == (1024, 1280)
        assert not image.getexif()
    with Image.open(BytesIO(small)) as image:
        assert image.size == (640, 800)


def test_transparent_upload_uses_paper_background():
    source = Image.new("RGBA", (640, 640), (0, 0, 0, 0))
    buffer = BytesIO()
    source.save(buffer, "PNG")
    large, _ = _encode_variants(buffer.getvalue())
    with Image.open(BytesIO(large)) as image:
        red, green, blue = image.getpixel((320, 320))
        assert red >= 245
        assert green >= 240
        assert blue >= 235


@pytest.mark.parametrize("width,height", [(639, 800), (800, 639)])
def test_upload_rejects_small_dimensions(width, height):
    source = Image.new("RGB", (width, height))
    buffer = BytesIO()
    source.save(buffer, "PNG")
    with pytest.raises(APIException, match="at least 640"):
        _encode_variants(buffer.getvalue())


class FakeDb:
    def __init__(self):
        self.args = None

    async def fetchrow(self, query, *args):
        self.args = args
        return {
            "slot": args[0],
            "image_url": args[1] or "/old.webp",
            "small_image_url": args[2] or "/old-small.webp",
            "alt_text": args[3],
            "caption": args[4],
            "focal_x": args[5],
            "focal_y": args[6],
        }


def test_metadata_save_preserves_existing_image_urls():
    db = FakeDb()
    image = asyncio.run(
        update_landing_image(
            db,
            "hero",
            image_urls=None,
            alt_text="  A new description  ",
            caption="  ",
            focal_x=30,
            focal_y=60,
        )
    )
    assert db.args[1:3] == (None, None)
    assert image["imageUrl"] == "/old.webp"
    assert image["altText"] == "A new description"
    assert image["caption"] == ""


def test_invalid_alt_is_rejected_before_database_write():
    db = FakeDb()
    with pytest.raises(APIException, match="Describe the image"):
        asyncio.run(
            update_landing_image(
                db,
                "ritual",
                image_urls=None,
                alt_text=" ",
                caption="",
                focal_x=50,
                focal_y=50,
            )
        )
    assert db.args is None
