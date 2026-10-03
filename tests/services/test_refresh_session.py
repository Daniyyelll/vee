import asyncio
import importlib.util
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import asyncpg
import pytest

from app.core.exceptions import APIException
from app.core.security import decode_access_token
from app.services.refresh_session import (
    create_refresh_session,
    revoke_refresh_session,
    rotate_refresh_session,
)


def test_refresh_tokens_are_stored_as_hashes_and_rotated():
    async def scenario():
        db = AsyncMock()

        @asynccontextmanager
        async def transaction():
            yield

        db.transaction = transaction
        user_id = uuid4()
        token, expiry = await create_refresh_session(db, user_id, 3)
        insert_args = db.execute.await_args.args
        assert token not in insert_args
        assert insert_args[3] == sha256(token.encode()).hexdigest()
        assert insert_args[4] == 3
        assert expiry > datetime.now(timezone.utc) + timedelta(days=13)

        family_id = uuid4()
        db.fetchrow.return_value = {
            "session_id": uuid4(),
            "family_id": family_id,
            "replaced_by_id": None,
            "revoked_at": None,
            "id": user_id,
            "name": "Buyer",
            "email": "buyer@example.com",
            "role": "CUSTOMER",
            "active": True,
            "address": None,
            "phone": None,
            "token_version": 3,
            "session_token_version": 3,
            "expires_at": expiry,
        }
        replacement, _, access, user = await rotate_refresh_session(db, token)
        select_args = db.fetchrow.await_args.args
        assert select_args[1] == sha256(token.encode()).hexdigest()
        persisted = [arg for call in db.execute.await_args_list for arg in call.args]
        assert sha256(replacement.encode()).hexdigest() in persisted
        assert token != replacement
        assert user["id"] == user_id
        assert decode_access_token(access)["ver"] == 3

        await revoke_refresh_session(db, replacement)
        assert db.execute.await_args.args[1] == sha256(replacement.encode()).hexdigest()

        db.fetchrow.return_value = None
        with pytest.raises(APIException) as error:
            await rotate_refresh_session(db, token)
        assert error.value.status_code == 401

    asyncio.run(scenario())


def test_refresh_sql_rotates_once_and_obeys_account_version():
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to a disposable PostgreSQL database")

    async def scenario():
        db = await asyncpg.connect(database_url)
        schema = f"test_refresh_{uuid4().hex}"
        try:
            await db.execute(f'CREATE SCHEMA "{schema}"')
            await db.execute(f'SET search_path TO "{schema}"')
            await db.execute(
                """
                CREATE TABLE "user" (
                    id UUID PRIMARY KEY,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL,
                    role TEXT NOT NULL,
                    active BOOLEAN NOT NULL DEFAULT TRUE,
                    address TEXT,
                    phone TEXT,
                    token_version INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            path = Path("migrations/versions/d4a7f6c20e91_refresh_sessions.py")
            spec = importlib.util.spec_from_file_location("refresh_migration", path)
            assert spec and spec.loader
            migration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration)
            statements = []
            migration.op = SimpleNamespace(execute=statements.append)
            migration.upgrade()
            for statement in statements:
                await db.execute(statement)
            await db.execute("ALTER TABLE refresh_session ADD COLUMN family_id UUID")
            await db.execute("UPDATE refresh_session SET family_id = id")
            await db.execute(
                "ALTER TABLE refresh_session ALTER COLUMN family_id SET NOT NULL, "
                "ADD COLUMN replaced_by_id UUID REFERENCES refresh_session (id), "
                "ADD COLUMN revoked_at TIMESTAMPTZ"
            )

            user_id = uuid4()
            await db.execute(
                'INSERT INTO "user" (id, name, email, role) VALUES ($1, $2, $3, $4)',
                user_id,
                "Buyer",
                "buyer@example.com",
                "CUSTOMER",
            )
            token, _ = await create_refresh_session(db, user_id, 0)
            replacement, _, _, _ = await rotate_refresh_session(db, token)
            with pytest.raises(APIException):
                await rotate_refresh_session(db, token)
            assert (await db.fetchval("SELECT COUNT(*) FROM refresh_session")) == 2
            assert (
                await db.fetchval(
                    "SELECT COUNT(*) FROM refresh_session WHERE revoked_at IS NOT NULL"
                )
                == 2
            )
            assert (
                await db.fetchval(
                    'SELECT token_version FROM "user" WHERE id = $1', user_id
                )
                == 1
            )
            with pytest.raises(APIException):
                await rotate_refresh_session(db, replacement)
        finally:
            try:
                await db.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            finally:
                await db.close()

    asyncio.run(scenario())
