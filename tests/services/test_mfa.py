import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.exceptions import APIException
from app.domain.enums import UserRole
from app.schemas.user import UserLogin
from app.services.mfa import (
    TOTP_PERIOD_SECONDS,
    _code,
    decrypt_secret,
    encrypt_secret,
    generate_secret,
    verify_code,
)
from app.services.staff_auth import verify_staff_login_mfa


def test_totp_secret_is_encrypted_and_used_codes_are_rejected():
    secret = generate_secret()
    sealed = encrypt_secret(secret)
    assert secret.encode() not in sealed
    assert decrypt_secret(sealed) == secret

    counter = int(time.time()) // TOTP_PERIOD_SECONDS
    code = _code(secret, counter)
    assert verify_code(secret, code, now=counter * TOTP_PERIOD_SECONDS) == counter
    assert (
        verify_code(
            secret,
            code,
            last_counter=counter,
            now=counter * TOTP_PERIOD_SECONDS,
        )
        is None
    )


def test_staff_login_requires_mfa_and_persists_the_counter():
    async def scenario():
        user = SimpleNamespace(id=uuid4(), role=UserRole.ADMIN)
        login = UserLogin(
            email="admin@example.com", password="correct horse battery staple"
        )
        db = AsyncMock()
        db.fetchrow.return_value = {
            "staff_mfa_secret": None,
            "staff_mfa_enabled": False,
            "staff_mfa_last_counter": None,
        }
        with pytest.raises(APIException) as required:
            await verify_staff_login_mfa(db, login, user)
        assert required.value.status_code == 403

        secret = generate_secret()
        counter = int(time.time()) // TOTP_PERIOD_SECONDS
        login.mfa_code = _code(secret, counter)
        db.fetchrow.return_value = {
            "staff_mfa_secret": encrypt_secret(secret),
            "staff_mfa_enabled": True,
            "staff_mfa_last_counter": None,
        }
        db.execute.return_value = "UPDATE 1"
        await verify_staff_login_mfa(db, login, user)
        assert db.execute.await_args.args[1:] == (counter, user.id)

    asyncio.run(scenario())
