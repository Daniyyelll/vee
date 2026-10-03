import uuid

import asyncpg
from fastapi import status

from app.core.exceptions import APIException
from app.schemas.category import CategoryCreate, CategoryUpdate
from app.utils.slugify import slugify

CATEGORY_COLUMNS = {
    "category_name": "category_name",
    "description": "description",
}


async def get_category_id_from_slug(
    db: asyncpg.Connection, category_slug: str
) -> uuid.UUID | None:
    return await db.fetchval("SELECT id FROM category WHERE slug = $1", category_slug)


async def create_category(
    db: asyncpg.Connection,
    body_data: CategoryCreate,
) -> dict:
    category_id = uuid.uuid4()
    category_slug = slugify(body_data.category_name)
    try:
        async with db.transaction():
            row = await db.fetchrow(
                """
                INSERT INTO category (id, category_name, description, slug)
                VALUES ($1, $2, $3, $4)
                RETURNING id, category_name, description, slug
                """,
                category_id,
                body_data.category_name,
                body_data.description,
                category_slug,
            )
    except asyncpg.UniqueViolationError as exc:
        if exc.constraint_name == "uq_category_slug":
            row = await db.fetchrow(
                """
                INSERT INTO category (id, category_name, description, slug)
                VALUES ($1, $2, $3, $4)
                RETURNING id, category_name, description, slug
                """,
                category_id,
                body_data.category_name,
                body_data.description,
                f"{category_slug[:218]}-{category_id}",
            )
            return dict(row)
        raise APIException(
            message="A category with this name already exists.",
            status_code=status.HTTP_409_CONFLICT,
        ) from exc

    return dict(row)


async def get_all_categories(db: asyncpg.Connection) -> list[dict]:
    rows = await db.fetch(
        """
        SELECT id, category_name, description, slug
        FROM "category"
        ORDER BY category_name
        """
    )
    return [dict(row) for row in rows]


async def update_category(
    db: asyncpg.Connection, category_id: uuid.UUID, body_data: CategoryUpdate
):
    update_data = body_data.model_dump(exclude_unset=True)

    assignments: list[str] = []
    values: list[object] = []

    for field, value in update_data.items():
        column = CATEGORY_COLUMNS.get(field)
        if not column:
            continue

        values.append(value)
        assignments.append(f"{column} = ${len(values)}")

    values.append(category_id)

    try:
        row = await db.fetchrow(
            f"""
            UPDATE "category"
            SET {", ".join(assignments)}
            WHERE id = ${len(values)}
            RETURNING id, category_name, description, slug
            """,
            *values,
        )
    except asyncpg.UniqueViolationError as exc:
        raise APIException(
            "A category with this name already exists.",
            status.HTTP_409_CONFLICT,
        ) from exc
    if row is None:
        raise APIException("Category not found.", status.HTTP_404_NOT_FOUND)
    return dict(row)


async def delete_category(db: asyncpg.Connection, category_id: uuid.UUID):
    try:
        result = await db.execute('DELETE FROM "category" WHERE id = $1', category_id)
    except asyncpg.ForeignKeyViolationError as exc:
        raise APIException(
            "Category contains products and cannot be deleted.",
            status.HTTP_409_CONFLICT,
        ) from exc
    if result == "DELETE 0":
        raise APIException("Category not found.", status.HTTP_404_NOT_FOUND)
