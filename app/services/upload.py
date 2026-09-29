import asyncio
import uuid
from io import BytesIO
from pathlib import Path

from fastapi import UploadFile, status
from PIL import Image, UnidentifiedImageError

from app.core.exceptions import APIException

MAX_IMAGE_SIZE = 5 * 1024 * 1024
IMAGE_EXTENSIONS = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}
MAX_IMAGE_PIXELS = 25_000_000


def _save_file(file_path: Path, contents: bytes) -> None:
    file_path.write_bytes(contents)


async def upload_file(file: UploadFile, upload_dir: Path) -> str:
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

    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / f"{uuid.uuid4()}{extension}"
    await asyncio.to_thread(_save_file, file_path, contents)
    return f"/uploads/products/{file_path.name}"


async def delete_uploaded_file(image_url: str, upload_dir: Path) -> None:
    filename = Path(image_url).name
    file_path = upload_dir / filename
    await asyncio.to_thread(file_path.unlink, missing_ok=True)
