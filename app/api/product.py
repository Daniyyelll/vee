from decimal import Decimal

import asyncpg
from fastapi import APIRouter, Depends, File, Form, Response, UploadFile, status

from app.api.dependencies import is_admin
from app.core.exceptions import APIException
from app.db.session import get_connection
from app.schemas.product import ProductCreate, ProductRead, ProductUpdate
from app.schemas.response import APIResponse
from app.services.category import get_category_id_from_slug
from app.services.product import (
    create_product,
    delete_product,
    get_all_products,
    get_product_by_slug,
    update_product,
)

router = APIRouter(prefix="/products", tags=["products"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def add_product(
    product_name: str = Form(alias="productName"),
    price: Decimal = Form(),
    stock_quantity: int = Form(alias="stockQuantity", ge=0),
    category_slug: str = Form(alias="categorySlug"),
    description: str | None = Form(default=None),
    image_file: UploadFile = File(alias="imageFile"),
    db: asyncpg.Connection = Depends(get_connection),
    _: dict = Depends(is_admin),
) -> APIResponse[dict]:

    category_id = await get_category_id_from_slug(db, category_slug)

    if category_id is None:
        raise APIException(
            status_code=status.HTTP_404_NOT_FOUND,
            message="Category not found",
        )

    product = ProductCreate(
        product_name=product_name,
        description=description,
        price=price,
        stock_quantity=stock_quantity,
        category_id=category_id,
    )

    created_product = await create_product(db, product, image_file)

    return APIResponse(
        status_code=status.HTTP_201_CREATED,
        message="Product Created",
        data=created_product,
    )


@router.get("", status_code=status.HTTP_200_OK)
async def get_products(
    db: asyncpg.Connection = Depends(get_connection),
) -> APIResponse[list[ProductRead]]:
    products = await get_all_products(db)

    return APIResponse(
        status_code=status.HTTP_200_OK,
        message="Products",
        data=products,
    )


@router.patch("/{product_slug}", status_code=status.HTTP_200_OK)
async def edit_product(
    product_slug: str,
    product_changes: ProductUpdate,
    db: asyncpg.Connection = Depends(get_connection),
    _: dict = Depends(is_admin),
) -> APIResponse[ProductRead]:
    info = await update_product(db, product_slug, product_changes)
    return APIResponse(
        status_code=status.HTTP_200_OK, message="Product Updated", data=info
    )


@router.get("/{product_slug}", status_code=status.HTTP_200_OK)
async def get_product(
    product_slug: str,
    db: asyncpg.Connection = Depends(get_connection),
) -> APIResponse[ProductRead]:
    product = await get_product_by_slug(db, product_slug)
    return APIResponse(status_code=status.HTTP_200_OK, message="Product", data=product)


@router.delete("/{product_slug}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_product(
    product_slug: str,
    db: asyncpg.Connection = Depends(get_connection),
    _: dict = Depends(is_admin),
) -> Response:
    await delete_product(db, product_slug)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
