"""Public landing image read and administrator publishing endpoint."""

import asyncpg
from fastapi import APIRouter, Depends, File, Form, Response, UploadFile, status

from app.api.dependencies import is_admin
from app.db.session import get_connection
from app.schemas.response import APIResponse
from app.services.audit import record_audit
from app.services.landing_image import (
    check_slot,
    discard_image,
    list_landing_images,
    prepare_image,
    update_landing_image,
)

router = APIRouter(prefix="/landing-images", tags=["landing images"])


@router.get("")
async def get_landing_images(
    response: Response,
    db: asyncpg.Connection = Depends(get_connection),
) -> APIResponse[list[dict]]:
    response.headers["Cache-Control"] = "no-store"
    return APIResponse(
        status_code=200,
        message="Landing images",
        data=await list_landing_images(db),
    )


@router.patch("/{slot}")
async def publish_landing_image(
    slot: str,
    alt_text: str = Form(alias="altText", min_length=1, max_length=240),
    caption: str = Form(default="", max_length=300),
    focal_x: int = Form(default=50, alias="focalX", ge=0, le=100),
    focal_y: int = Form(default=50, alias="focalY", ge=0, le=100),
    image_file: UploadFile | None = File(default=None, alias="imageFile"),
    db: asyncpg.Connection = Depends(get_connection),
    admin: dict = Depends(is_admin),
) -> APIResponse[dict]:
    check_slot(slot)
    urls = await prepare_image(image_file, slot) if image_file else None
    try:
        async with db.transaction():
            image = await update_landing_image(
                db,
                slot,
                image_urls=urls,
                alt_text=alt_text,
                caption=caption,
                focal_x=focal_x,
                focal_y=focal_y,
            )
            await record_audit(
                db,
                admin,
                "landing_image.published",
                "landing_image",
                slot,
                details={"image_changed": urls is not None},
            )
    except Exception:
        if urls:
            await discard_image(urls)
        raise
    return APIResponse(
        status_code=status.HTTP_200_OK,
        message="Landing image published",
        data=image,
    )
