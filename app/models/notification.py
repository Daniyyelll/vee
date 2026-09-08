import enum
import uuid
from datetime import datetime

from sqlmodel import Column, DateTime, Field, SQLModel, text


class NotificationType(enum.StrEnum):
    ORDER_PLACED = "order_placed"
    ORDER_CONFIRMED = "order_confirmed"
    ORDER_SHIPPED = "order_shipped"
    ORDER_DELIVERED = "order_delivered"
    ORDER_CANCELLED = "order_cancelled"
    PAYMENT_SUCCESSFUL = "payment_successful"
    PAYMENT_FAILED = "payment_failed"
    REFUND_ISSUED = "refund_issued"
    ACCOUNT_CREATED = "account_created"
    PASSWORD_CHANGED = "password_changed"
    PROMOTION = "promotion"


class Notification(SQLModel, table=True):
    __tablename__ = "notification"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)

    # Destination
    recepient_email: str = Field(index=True)

    title: str = Field()
    content: str = Field()

    notification_type: NotificationType = Field(default=NotificationType.ORDER_PLACED)

    created_at: datetime = Field(
        default=None,
        sa_column=Column(
            DateTime(timezone=True),
            server_default=text("NOW()"),
            nullable=False,
        ),
    )
