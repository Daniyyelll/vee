from pydantic import BaseModel, ConfigDict, EmailStr
from pydantic.alias_generators import to_camel

from app.models.notification import NotificationType


class Notification(BaseModel):
    recipient_email: EmailStr
    title: str
    content: str
    notification_type: NotificationType

    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
        from_attributes=True,
    )
