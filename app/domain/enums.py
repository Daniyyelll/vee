"""Application enums independent of the persistence implementation."""

import enum


class UserRole(enum.StrEnum):
    ADMIN = "admin"
    CUSTOMER = "customer"
    DELIVERY = "delivery"


class OrderStatus(enum.StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class DeliveryArea(enum.StrEnum):
    CAIRO = "Cairo"
    NEW_CAIRO = "New Cairo"
    GIZA = "Giza"


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


class Currency(enum.StrEnum):
    EGP = "EGP"
    SAR = "SAR"
    AED = "AED"


class PaymentStatus(enum.StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"
    CANCELLED = "cancelled"


class PaymentMethod(enum.StrEnum):
    CASH = "Cash"


class ReportStatus(enum.StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"
