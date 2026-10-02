"""SMTP delivery for messages claimed from the transactional outbox."""

import logging
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import aiosmtplib
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.core.config import settings

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
jinja_env = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR), autoescape=select_autoescape(["html"])
)
logger = logging.getLogger(__name__)


async def _send_email(
    email: str, subject: str, template_name: str, fallback: str, **context: Any
) -> bool:
    try:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = settings.mail_from
        message["To"] = email
        message.set_content(fallback)
        message.add_alternative(
            jinja_env.get_template(template_name).render(**context), subtype="html"
        )
        await aiosmtplib.send(
            message,
            hostname=settings.mail_host,
            port=int(settings.mail_port),
            username=settings.mail_user,
            password=settings.mail_pass,
            start_tls=True,
            timeout=10,
        )
        return True
    except Exception:
        logger.exception("Email delivery failed")
        return False


async def send_reset_password_email(
    email: str, name: str, code: str, reset_url: str
) -> bool:
    return await _send_email(
        email,
        "Password reset request",
        "reset-password.html",
        f"Hello {name}, use this link within 30 minutes: {reset_url}",
        name=name,
        code=code,
        reset_url=reset_url,
    )


async def send_order_status_update_email(email: str, name: str, order: Any) -> bool:
    return await _send_email(
        email,
        f"Update: Order #{order.order_number} is now {order.status.value}",
        "order-status.html",
        f"Hello {name}, order #{order.order_number} is {order.status.value}.",
        name=name,
        order_id=order.order_number,
        status=order.status.value.upper(),
        address=order.shipping_address,
        delivery_area=order.delivery_area,
        total_price=order.total_price,
        items=order.items,
    )


async def send_order_confirmation_email(email: str, name: str, order: Any) -> bool:
    return await _send_email(
        email,
        f"Confirmation: Order #{order.order_number}",
        "order_confirmation.html",
        f"Hello {name}, order #{order.order_number} totals {order.total_price}.",
        name=name,
        order_id=order.order_number,
        total=order.total_price,
        address=order.shipping_address,
        delivery_area=order.delivery_area,
    )
