from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator
from pydantic.alias_generators import to_camel


class CouponCreate(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        str_strip_whitespace=True,
        extra="forbid",
    )

    code: str | None = Field(default=None, min_length=4, max_length=64)
    kind: str = Field(pattern="^(percent|free_shipping)$")
    discount_percent: Decimal | None = Field(
        default=None, gt=0, lt=100, max_digits=5, decimal_places=2
    )
    starts_at: datetime | None = None
    expires_at: datetime | None = None
    assigned_user_id: UUID | None = None
    max_uses: int | None = Field(default=None, ge=1, le=2147483647)

    @model_validator(mode="after")
    def validate_coupon(self):
        if not (
            self.starts_at or self.expires_at or self.assigned_user_id or self.max_uses
        ):
            raise ValueError("Set a validity date, usage limit, or customer")
        if (self.kind == "percent") != (self.discount_percent is not None):
            raise ValueError("Only percentage coupons need discountPercent")
        if self.starts_at and self.expires_at and self.starts_at >= self.expires_at:
            raise ValueError("Coupon end must be after its start")
        for moment in (self.starts_at, self.expires_at):
            if moment and moment.tzinfo is None:
                raise ValueError("Coupon dates must include a timezone")
        return self


class CouponRead(CouponCreate):
    id: UUID
    code: str
    active: bool
    created_at: datetime
    uses_count: int = Field(ge=0)

    @computed_field(alias="remainingUses")
    @property
    def remaining_uses(self) -> int | None:
        return None if self.max_uses is None else self.max_uses - self.uses_count
