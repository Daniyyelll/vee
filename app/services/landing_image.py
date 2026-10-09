"""Validate, optimize, and publish the fixed landing image slots."""

import uuid
from io import BytesIO

import asyncpg
from fastapi import UploadFile, status
from PIL import Image, ImageOps, UnidentifiedImageError
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.exceptions import APIException
from app.services.supabase import get_supabase_client

MAX_FILE_SIZE = 5 * 1024 * 1024
MAX_PIXELS = 25_000_000
SLOTS = {"hero", "ritual"}


def check_slot(slot: str) -> None:
    if slot not in SLOTS:
        raise APIException("Landing image slot not found.", status.HTTP_404_NOT_FOUND)


def _encode_variants(contents: bytes) -> tuple[bytes, bytes]:
    try:
        with Image.open(BytesIO(contents)) as source:
            source.verify()
        with Image.open(BytesIO(contents)) as source:
            if source.format not in {"PNG", "JPEG", "WEBP"}:
                raise APIException(
                    "Upload a PNG, JPEG, or WebP image.",
                    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                )
            if source.width * source.height > MAX_PIXELS:
                raise APIException(
                    "Image dimensions must be 25 megapixels or smaller.",
                    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                )
            if min(source.width, source.height) < 640:
                raise APIException(
                    "Image width and height must each be at least 640 pixels."
                )
            oriented = ImageOps.exif_transpose(source)
            rgba = oriented.convert("RGBA")
            rgb = Image.new("RGB", rgba.size, "#faf7f2")
            rgb.paste(rgba, mask=rgba.getchannel("A"))
            variants = []
            for bounds in ((1024, 1600), (640, 1000)):
                resized = rgb.copy()
                resized.thumbnail(bounds, Image.Resampling.LANCZOS)
                output = BytesIO()
                resized.save(output, "WEBP", quality=82, method=6)
                variants.append(output.getvalue())
            return variants[0], variants[1]
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise APIException(
            "Upload a valid PNG, JPEG, or WebP image.",
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        ) from exc


def _upload_variants(slot: str, variants: tuple[bytes, bytes]) -> tuple[str, str]:
    storage = get_supabase_client().storage.from_(settings.supabase_site_bucket)
    prefix = f"landing/{slot}/{uuid.uuid4()}"
    paths = [f"{prefix}-1024.webp", f"{prefix}-640.webp"]
    uploaded = []
    try:
        for path, content in zip(paths, variants, strict=True):
            storage.upload(
                path,
                content,
                {
                    "content-type": "image/webp",
                    "cache-control": "31536000",
                    "upsert": "false",
                },
            )
            uploaded.append(path)
        return storage.get_public_url(paths[0]), storage.get_public_url(paths[1])
    except Exception as exc:
        if uploaded:
            try:
                storage.remove(uploaded)
            except Exception:
                pass
        raise APIException(
            "Image storage is temporarily unavailable.",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exc


def _delete_variants(urls: tuple[str, str]) -> None:
    from urllib.parse import unquote, urlsplit

    prefix = f"/storage/v1/object/public/{settings.supabase_site_bucket}/"
    paths = [
        unquote(urlsplit(url).path)[len(prefix) :]
        for url in urls
        if unquote(urlsplit(url).path).startswith(prefix)
    ]
    if paths:
        try:
            get_supabase_client().storage.from_(settings.supabase_site_bucket).remove(
                paths
            )
        except Exception:
            pass


async def prepare_image(file: UploadFile, slot: str) -> tuple[str, str]:
    contents = await file.read(MAX_FILE_SIZE + 1)
    if len(contents) > MAX_FILE_SIZE:
        raise APIException(
            "Image must be 5 MB or smaller.",
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        )
    variants = await run_in_threadpool(_encode_variants, contents)
    return await run_in_threadpool(_upload_variants, slot, variants)


async def discard_image(urls: tuple[str, str]) -> None:
    await run_in_threadpool(_delete_variants, urls)


async def list_landing_images(db: asyncpg.Connection) -> list[dict]:
    rows = await db.fetch(
        """
        SELECT slot, image_url, small_image_url, alt_text, caption,
               focal_x, focal_y
        FROM landing_image ORDER BY slot
        """
    )
    return [
        {
            "slot": row["slot"],
            "imageUrl": row["image_url"],
            "smallImageUrl": row["small_image_url"],
            "altText": row["alt_text"],
            "caption": row["caption"],
            "focalX": row["focal_x"],
            "focalY": row["focal_y"],
        }
        for row in rows
    ]


async def update_landing_image(
    db: asyncpg.Connection,
    slot: str,
    *,
    image_urls: tuple[str, str] | None,
    alt_text: str,
    caption: str,
    focal_x: int,
    focal_y: int,
) -> dict:
    check_slot(slot)
    if not alt_text.strip():
        raise APIException("Describe the image for screen reader users.")
    if len(alt_text.strip()) > 240 or len(caption.strip()) > 300:
        raise APIException("Image description or caption is too long.")
    if not 0 <= focal_x <= 100 or not 0 <= focal_y <= 100:
        raise APIException("Image focus must be between 0 and 100.")

    row = await db.fetchrow(
        """
        UPDATE landing_image
        SET image_url = COALESCE($2, image_url),
            small_image_url = COALESCE($3, small_image_url),
            alt_text = $4, caption = $5,
            focal_x = $6, focal_y = $7, updated_at = now()
        WHERE slot = $1
        RETURNING slot, image_url, small_image_url, alt_text, caption,
                  focal_x, focal_y
        """,
        slot,
        image_urls[0] if image_urls else None,
        image_urls[1] if image_urls else None,
        alt_text.strip(),
        caption.strip(),
        focal_x,
        focal_y,
    )
    if row is None:
        raise APIException("Landing image slot not found.", status.HTTP_404_NOT_FOUND)
    return {
        "slot": row["slot"],
        "imageUrl": row["image_url"],
        "smallImageUrl": row["small_image_url"],
        "altText": row["alt_text"],
        "caption": row["caption"],
        "focalX": row["focal_x"],
        "focalY": row["focal_y"],
    }
