import uuid
from io import BytesIO
from urllib.parse import unquote, urlsplit

from fastapi import UploadFile, status
from PIL import Image, UnidentifiedImageError

from app.core.config import settings
from app.core.exceptions import APIException
from app.services.supabase import get_supabase_client

MAX_IMAGE_SIZE = 5 * 1024 * 1024
IMAGE_EXTENSIONS = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}
MAX_IMAGE_PIXELS = 25_000_000


async def upload_file(file: UploadFile) -> str:
    contents = await file.read(MAX_IMAGE_SIZE + 1)
    if len(contents) > MAX_IMAGE_SIZE:
        raise APIException(
            "Image must be 5 MB or smaller.", status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
        )

    try:
        with Image.open(BytesIO(contents)) as image:
            image.verify()
        with Image.open(BytesIO(contents)) as image:
            image_format = image.format
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise APIException(
                    "Image dimensions must be 25 megapixels or smaller.",
                    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                )
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise APIException(
            "Upload a valid PNG, JPEG, or WebP image.",
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        ) from exc

    extension = IMAGE_EXTENSIONS.get(image_format)
    if extension is None:
        raise APIException(
            "Upload a PNG, JPEG, or WebP image.",
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        )

    object_path = f"products/{uuid.uuid4()}{extension}"
    try:
        get_supabase_client().storage.from_(settings.supabase_product_bucket).upload(
            object_path,
            contents,
            {
                "content-type": file.content_type or "application/octet-stream",
                "cache-control": "31536000",
                "upsert": "false",
            },
        )
    except Exception as exc:
        raise APIException(
            "Image storage is temporarily unavailable.",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exc

    return (
        get_supabase_client()
        .storage.from_(settings.supabase_product_bucket)
        .get_public_url(object_path)
    )


async def delete_uploaded_file(image_url: str) -> None:
    """Delete a product image from Supabase after a failed database write."""
    path_prefix = f"/storage/v1/object/public/{settings.supabase_product_bucket}/"
    path = unquote(urlsplit(image_url).path)
    if not path.startswith(path_prefix):
        return

    object_path = path[len(path_prefix) :]
    if not object_path:
        return

    try:
        get_supabase_client().storage.from_(settings.supabase_product_bucket).remove(
            [object_path]
        )
    except Exception:
        # Cleanup must not hide the original database error.
        return
