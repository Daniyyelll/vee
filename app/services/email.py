import logging
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import aiosmtplib
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.core.config import settings
from app.core.exceptions import APIException

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
jinja_env = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR), autoescape=select_autoescape(["html"])
)
logger = logging.getLogger(__name__)


async def send_welcome_email(email: str, name: str):
    print("Inside send_welcome_email")

    print(f"Mail Host: {settings.mail_host}")

    # SETUP UP OUR EMAIL INSTANCE
    message = EmailMessage()
    message["Subject"] = "Welcome to Vee"
    message["from"] = settings.mail_from
    message["to"] = email

    # render & BUILD the HTML template (welcome.html)
    try:
        template = jinja_env.get_template("welcome.html")
        html_content = template.render(name=name, frontendUrl=settings.FRONTEND_URL)
        message.add_alternative(html_content, subtype="html")
    except Exception as e:
        message.set_content(f"Hello {name}, welcome to Vee")
        print(f"⚠️ Template Error: {e}")

    # NOW SENDING THE EMAIL OUR
    try:
        await aiosmtplib.send(
            message,
            hostname=settings.mail_host,
            port=int(settings.mail_port),
            username=settings.mail_user,
            password=settings.mail_pass,
        )
        print("welcome email sent successfully")

    except Exception as e:
        print(f"Error sending welcome email out: {e}")
        raise APIException(
            message=f"Error sending email {e}",
            status_code=500,
        )


async def send_reset_password_email(email: str, name: str, code: str, reset_url: str):
    print("Inside send_reset_password_email")

    # SETUP UP OUR EMAIL INSTANCE
    message = EmailMessage()
    message["Subject"] = "Password Reset Request - Action Required"
    message["from"] = settings.mail_from
    message["to"] = email

    # render & BUILD the HTML template (welcome.html)
    try:
        template = jinja_env.get_template("reset-password.html")
        html_content = template.render(name=name, code=code, reset_url=reset_url)
        message.add_alternative(html_content, subtype="html")

    except Exception as e:
        # Fallback text
        message.set_content(
            f"Hello {name}, your reset code is: {code}. Link: {reset_url}"
        )
        print(f"⚠️ Template Error: {e}")

    # NOW SENDING THE EMAIL OUR
    try:
        await aiosmtplib.send(
            message,
            hostname=settings.mail_host,
            port=int(settings.mail_port),
            username=settings.mail_user,
            password=settings.mail_pass,
        )
        print("Forgot Password email sent successfully")

    except Exception as e:
        print(f"Error sending Forgot Password email out: {e}")

        raise APIException(
            message=f"Error sending email {e}",
            status_code=500,
        )


async def _send_order_email(email: str, subject: str, template_name: str, **context):
    """Best-effort post-commit notification; SMTP cannot roll back an order."""
    try:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = settings.mail_from
        message["To"] = email
        html = jinja_env.get_template(template_name).render(**context)
        message.add_alternative(html, subtype="html")
        await aiosmtplib.send(
            message,
            hostname=settings.mail_host,
            port=int(settings.mail_port),
            username=settings.mail_user,
            password=settings.mail_pass,
            start_tls=True,
            timeout=10,
        )
    except Exception:
        logger.exception("Order email failed")


async def send_order_status_update_email(email: str, name: str, order: Any):
    await _send_order_email(
        email,
        f"Update: Order #{order.order_number} is now {order.status.value}",
        "order-status.html",
        name=name,
        order_id=order.order_number,
        status=order.status.value.upper(),
        address=order.shipping_address,
        total_price=order.total_price,
        items=order.items,
    )


async def send_order_confirmation_email(email: str, name: str, order: Any):
    await _send_order_email(
        email,
        f"Confirmation: Order #{order.order_number}",
        "order_confirmation.html",
        name=name,
        order_id=order.order_number,
        total=order.total_price,
        address=order.shipping_address,
    )


async def notify_delivery_team_of_order(order: Any, customer_name: str):

    try:
        template = jinja_env.get_template("delivery_person_order_notification.html")

        html_content = template.render(
            customer_name=customer_name,
            order_id=order.id,
            order_status=order.status,
            payment_status=order.payment.status if order.payment else "Unknown",
            total=order.total_price,
            address=order.shipping_address,
            items=order.items,  # This allows the admin to see the product list
            order_date=order.created_at.strftime("%Y-%m-%d %H:%M"),
        )

        message = EmailMessage()
        message["Subject"] = f"🚨 New Order Received: #{order.id}"
        message["From"] = settings.MAIL_FROM
        message["To"] = (
            settings.DELIVERY_PERSON_EMAIL
        )  # Ensure this is in your delibery email
        message.add_alternative(html_content, subtype="html")

        await aiosmtplib.send(
            message,
            hostname=settings.mail_host,
            port=int(settings.mail_port),
            username=settings.mail_user,
            password=settings.mail_pass,
            start_tls=True,
        )
        print(f"✅ Delivery team notified of Order #{order.id}")
    except Exception as e:
        print(f"❌ Delivery Email Error to notify Delivery Man: {e}")


async def send_payment_notification(
    email: str,
    name: str,
    order_id: int,
    status: str,
    amount: str = None,
    error: str = None,
):
    template_name = (
        "payment-success.html" if status == "success" else "payment-failed.html"
    )
    subject = (
        f"Payment Successful - Order #{order_id}"
        if status == "success"
        else f"Payment Failed - Order #{order_id}"
    )

    try:
        template = jinja_env.get_template(template_name)
        html_content = template.render(
            name=name,
            order_id=order_id,
            amount=amount,
            currency="USD",
            error_message=error,
        )

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = settings.MAIL_FROM
        message["To"] = email
        message.add_alternative(html_content, subtype="html")

        await aiosmtplib.send(
            message,
            hostname=settings.mail_host,
            port=int(settings.mail_port),
            username=settings.mail_user,
            password=settings.mail_pass,
            start_tls=True,
        )
        print("success sending payment email out")

    except Exception as e:
        print(f"❌ Email error: {e}")
