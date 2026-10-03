"""Append-only security and business audit events."""

import json
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from app.core.request_context import request_id_context


async def record_audit(
    db: asyncpg.Connection,
    actor: dict[str, Any] | None,
    action: str,
    entity_type: str,
    entity_id: object | None,
    *,
    details: dict[str, Any] | None = None,
) -> None:
    actor_id = actor.get("id") if actor else None
    if actor_id == UUID(int=0):
        actor_id = None
    await db.execute(
        """
        INSERT INTO audit_event (
            id, actor_user_id, action, entity_type, entity_id, request_id, details
        ) VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
        """,
        uuid4(),
        actor_id,
        action,
        entity_type,
        str(entity_id) if entity_id is not None else None,
        request_id_context.get(),
        json.dumps(details or {}, default=str),
    )
