import uuid
from datetime import datetime

from sqlmodel import Column, DateTime, Field, SQLModel, text


class ResetCode(SQLModel, table=True):
    __tablename__ = "reset_code"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    email: str
    code: str
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=text("NOW()"),
            nullable=False,
        ),
    )
    expires_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=text("NOW() + INTERVAL '5 minutes'"),
            nullable=False,
        ),
    )
