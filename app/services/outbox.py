"""Durable email queue stored in the same transaction as domain changes."""

import asyncio
import base64
import json
import logging
from hashlib import sha256
from uuid import UUID, uuid4

import asyncpg
from cryptography.fernet import Fernet

from app.core.config import settings
from app.services.email import (
    send_order_confirmation_email,
    send_order_status_update_email,
    send_reset_password_email,
)

logger = logging.getLogger(__name__)
FERNET = Fernet(
    base64.urlsafe_b64encode(sha256(settings.secret_jwt_key.encode()).digest())
)


async def enqueue_email(db: asyncpg.Connection, kind: str, payload: dict) -> None:
    if kind == "password_reset":
        payload = {"sealed": FERNET.encrypt(json.dumps(payload).encode()).decode()}
    await db.execute(
        "INSERT INTO email_outbox (id, kind, payload) VALUES ($1, $2, $3::jsonb)",
        uuid4(),
        kind,
        json.dumps(payload),
    )


async def _send(db: asyncpg.Connection, kind: str, payload: dict) -> bool:
    if kind == "password_reset":
        payload = json.loads(FERNET.decrypt(payload["sealed"]))
        valid = await db.fetchval(
            "SELECT 1 FROM reset_code WHERE code = $1 AND expires_at > NOW()",
            sha256(payload["token"].encode()).hexdigest(),
        )
        if not valid:
            return True
        return await send_reset_password_email(
            payload["email"],
            payload["name"],
            payload["token"],
            payload["reset_url"],
        )
    from app.services.order import ORDER_COLUMNS, _read_orders

    order_id = UUID(payload["order_id"])
    row = await db.fetchrow(
        f"""SELECT {ORDER_COLUMNS} FROM "order" o
        LEFT JOIN "user" u ON u.id = o.user_id WHERE o.id = $1""",
        order_id,
    )
    if row is None:
        return True
    order = (await _read_orders(db, [row]))[0]
    if kind == "order_status":
        from app.domain.enums import OrderStatus

        order.status = OrderStatus(payload["status"])
    email = str(order.user.email) if order.user else str(order.guest_email)
    name = order.recipient_name or (order.user.name if order.user else order.guest_name)
    if kind == "order_confirmation":
        return await send_order_confirmation_email(email, name, order)
    if kind == "order_status":
        return await send_order_status_update_email(email, name, order)
    raise ValueError(f"Unknown email outbox kind: {kind}")


async def process_email_outbox(db: asyncpg.Connection) -> int:
    processed = 0
    async with db.transaction():
        rows = await db.fetch(
            """
            SELECT id, kind, payload, attempts FROM email_outbox
            WHERE sent_at IS NULL AND next_attempt_at <= NOW()
            ORDER BY created_at LIMIT 10 FOR UPDATE SKIP LOCKED
            """
        )
        for row in rows:
            try:
                payload = row["payload"]
                if isinstance(payload, str):
                    payload = json.loads(payload)
                sent = await _send(db, row["kind"], payload)
            except Exception:
                sent = False
                logger.exception(
                    "Email outbox delivery failed", extra={"email_id": str(row["id"])}
                )
            if sent:
                await db.execute(
                    "UPDATE email_outbox SET sent_at = NOW(), payload = '{}'::jsonb "
                    "WHERE id = $1",
                    row["id"],
                )
                processed += 1
            else:
                await db.execute(
                    """
                    UPDATE email_outbox SET attempts = attempts + 1,
                        next_attempt_at = NOW() +
                            LEAST(3600, 10 * power(2, LEAST(attempts, 8)))
                            * INTERVAL '1 second'
                    WHERE id = $1
                    """,
                    row["id"],
                )
    return processed


async def maintenance_worker(pool: asyncpg.Pool) -> None:
    from app.services.order import expire_pending_orders

    while True:
        try:
            async with pool.acquire() as db:
                await expire_pending_orders(db)
                await process_email_outbox(db)
                await db.execute(
                    "DELETE FROM rate_limit WHERE reset_at < NOW() - INTERVAL '1 day'"
                )
                await db.execute(
                    "DELETE FROM reset_code WHERE expires_at < NOW() - INTERVAL '1 day'"
                )
                await db.execute(
                    "DELETE FROM email_outbox "
                    "WHERE sent_at < NOW() - INTERVAL '90 days'"
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Maintenance worker failed")
        await asyncio.sleep(30)
