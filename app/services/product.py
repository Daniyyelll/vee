import uuid
from datetime import datetime, timezone
from uuid import UUID

import asyncpg
from fastapi import UploadFile, status

from app.core.config import settings
from app.core.exceptions import APIException
from app.schemas.product import ProductCreate, ProductRead, ProductUpdate
from app.services.category import get_category_id_from_slug
from app.services.upload import delete_uploaded_file, upload_file
from app.utils.slugify import slugify

product_cols = """
    product_name, description, price, stock_quantity, image_url
"""


# helpers
async def get_product_id_by_slug(db: asyncpg.Connection, product_slug: str) -> UUID:
    product_id = await db.fetchval(
        "SELECT id FROM product WHERE product_slug = $1",
        product_slug,
    )
    if product_id is None:
        raise APIException("Product not found.", status.HTTP_404_NOT_FOUND)
    return product_id


async def create_product(
    db: asyncpg.Connection, product: ProductCreate, image_file: UploadFile
):
    upload_dir = settings.product_upload_dir

    image_path = await upload_file(image_file, upload_dir)

    try:
        row = await db.fetchrow(
            """
            INSERT INTO product (
                id, product_name, description, price, stock_quantity,
                image_url, created_at, category_id, product_slug
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING id, product_name, description, price, stock_quantity,
                      image_url, created_at, category_id, product_slug
    """,
            uuid.uuid4(),
            product.product_name,
            product.description,
            product.price,
            product.stock_quantity,
            image_path,
            datetime.now(timezone.utc),
            product.category_id,
            slugify(product.product_name),
        )

    except asyncpg.ForeignKeyViolationError as exc:
        await delete_uploaded_file(image_path, upload_dir)
        raise APIException(
            "The selected category does not exist.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        ) from exc
    except asyncpg.UniqueViolationError as exc:
        await delete_uploaded_file(image_path, upload_dir)
        raise APIException(
            "A product with this name already exists.", status.HTTP_409_CONFLICT
        ) from exc
    except Exception:
        await delete_uploaded_file(image_path, upload_dir)
        raise

    return dict(row)


async def get_all_products(
    db: asyncpg.Connection, category_slug: str | None = None
) -> list[ProductRead]:
    if category_slug is not None:
        category_id = get_category_id_from_slug(category_slug)

        rows = await db.fetch(
            f"""
            SELECT {product_cols} FROM product
            WHERE category_id = $1;
            """,
            category_id,
        )

    else:
        rows = await db.fetch(
            f"""
            SELECT {product_cols} FROM product;
            """
        )

    return [dict(product) for product in rows]


async def get_product_by_slug(db: asyncpg.Connection, product_slug: str) -> ProductRead:
    product_id = await get_product_id_by_slug(db, product_slug)

    product = await db.fetchrow(
        """
        SELECT product_name, description, price, stock_quantity, image_url
        FROM product
        WHERE id = $1;
        """,
        product_id,
    )

    return dict(product)


async def update_product(
    db: asyncpg.Connection, product_slug: str, product: ProductUpdate
):
    product_name: bool = False
    changes = product.model_dump(exclude_unset=True)

    assignments: list[str] = []
    values: list[object] = []

    for field, value in changes.items():
        if field == "product_name":
            product_name = True
        values.append(value)
        assignments.append(f"{field} = ${len(values)}")

    if not assignments:
        raise APIException(
            "Provide at least one profile field.", status.HTTP_400_BAD_REQUEST
        )

    if product_name:
        # Maintain Slug when updating Name
        values.append(slugify(product.product_name))
        assignments.append(f"product_slug = ${len(values)}")

    product_id = await get_product_id_by_slug(db, product_slug)
    values.append(product_id)

    row = await db.fetchrow(
        f"""
        UPDATE product
        SET {", ".join(assignments)}
        WHERE id = ${len(values)}
        RETURNING {product_cols}
        """,
        *values,
    )
    if row is None:
        raise APIException("Product not found.", status.HTTP_404_NOT_FOUND)

    return dict(row)


async def delete_product(db: asyncpg.Connection, product_slug: str):
    product_id = await get_product_id_by_slug(db, product_slug)

    info = await db.execute(
        """
        DELETE FROM product WHERE id = $1;""",
        product_id,
    )
    return info
