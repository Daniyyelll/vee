import uuid

import asyncpg
from fastapi import status

from app.core.exceptions import APIException
from app.schemas.category import CategoryCreate, CategoryUpdate

CATEGORY_COLUMNS = {
    "category_name": "category_name",
    "description": "description",
}


async def get_category_id_from_slug(
    db: asyncpg.Connection, category_slug: str
) -> uuid.UUID:
    category_id = await db.fetchval(
        """
        SELECT id FROM category WHERE category_slug = $1""",
        category_slug,
    )

    return category_id


async def create_category(
    db: asyncpg.Connection,
    body_data: CategoryCreate,
) -> dict:
    try:
        row = await db.fetchrow(
            """
            INSERT INTO category (id, category_name, description)
            VALUES ($1, $2, $3)
            RETURNING id, category_name, description
            """,
            uuid.uuid4(),
            body_data.category_name,
            body_data.description,
        )
    except asyncpg.UniqueViolationError as exc:
        raise APIException(
            message="A category with this name already exists.",
            status_code=status.HTTP_409_CONFLICT,
        ) from exc

    return dict(row)


async def get_all_categories(db: asyncpg.Connection) -> list[dict]:
    rows = await db.fetch(
        """
        SELECT id, category_name, description
        FROM "category"
        ORDER BY category_name
        """
    )
    return [dict(row) for row in rows]


async def update_category(
    db: asyncpg.Connection, category_id: uuid.UUID, body_data: CategoryUpdate
):
    update_data = body_data.model_dump(exclude_unset=True, exclude_none=True)

    assignments: list[str] = []
    values: list[object] = []

    for field, value in update_data.items():
        column = CATEGORY_COLUMNS.get(field)
        if not column:
            continue

        values.append(value)
        assignments.append(f"{column} = ${len(values)}")

    values.append(category_id)

    row = await db.fetchrow(
        f"""
        UPDATE "category"
        SET {", ".join(assignments)}
        WHERE id = ${len(values)}
        RETURNING id, category_name, description
        """,
        *values,
    )

    return row


async def delete_category(db: asyncpg.Connection, category_id: uuid.UUID):
    await db.execute(
        """DELETE FROM "category" WHERE id = $1""",
        category_id,
    )
