import asyncio
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import APIException
from app.schemas.user import UserCreate
from app.services.user import register_user


@pytest.mark.parametrize("role", ["admin", "delivery"])
def test_public_registration_rejects_privileged_roles(role):
    db = AsyncMock()
    request = UserCreate(
        name="Attacker", email="attacker@example.com", password="secret", role=role
    )
    with pytest.raises(APIException) as error:
        asyncio.run(register_user(db, request))
    assert error.value.status_code == 403
    db.fetchrow.assert_not_awaited()
