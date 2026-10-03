import asyncio
from uuid import uuid4

from app.domain.enums import UserRole
from app.services.order import list_orders


def test_profile_order_history_filters_to_owner_even_for_staff():
    class Database:
        def __init__(self):
            self.arguments = None

        async def fetch(self, _query, *arguments):
            self.arguments = arguments
            return []

    async def scenario():
        db = Database()
        user = {"id": uuid4(), "role": UserRole.ADMIN}
        assert await list_orders(db, user, limit=10, mine_only=True) == []
        assert db.arguments == ("admin", user["id"], None, 10, 0, True)

        assert await list_orders(db, user) == []
        assert db.arguments[0] == "admin"
        assert db.arguments[-1] is False

    asyncio.run(scenario())
