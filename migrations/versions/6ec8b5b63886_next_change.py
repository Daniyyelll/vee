"""Create the initial e-commerce schema with PostgreSQL DDL.

Revision ID: 6ec8b5b63886
Revises: beff147ec96a
"""

from alembic import op

revision = "6ec8b5b63886"
down_revision = "beff147ec96a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in """
        CREATE TYPE notificationtype AS ENUM (
            'ORDER_PLACED', 'ORDER_CONFIRMED', 'ORDER_SHIPPED',
            'ORDER_DELIVERED', 'ORDER_CANCELLED', 'PAYMENT_SUCCESSFUL',
            'PAYMENT_FAILED', 'REFUND_ISSUED', 'ACCOUNT_CREATED',
            'PASSWORD_CHANGED', 'PROMOTION'
        );
        CREATE TYPE userrole AS ENUM ('ADMIN', 'CUSTOMER', 'DELIVERY');
        CREATE TYPE orderstatus AS ENUM (
            'PENDING', 'PROCESSING', 'SHIPPED', 'DELIVERED', 'CANCELLED'
        );
        CREATE TYPE currency AS ENUM ('EGP', 'SAR', 'AED');
        CREATE TYPE paymentstatus AS ENUM (
            'PENDING', 'COMPLETED', 'FAILED', 'REFUNDED', 'CANCELLED'
        );
        CREATE TYPE paymentmethod AS ENUM ('CASH', 'INSTAPAY');

        CREATE TABLE category (
            id UUID PRIMARY KEY,
            category_name VARCHAR NOT NULL,
            description VARCHAR
        );
        CREATE UNIQUE INDEX ix_category_category_name
            ON category (category_name);

        CREATE TABLE notification (
            id UUID PRIMARY KEY,
            recipient_email VARCHAR NOT NULL,
            title VARCHAR NOT NULL,
            content VARCHAR NOT NULL,
            notification_type notificationtype NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX ix_notification_recipient_email
            ON notification (recipient_email);

        CREATE TABLE reset_code (
            id UUID PRIMARY KEY,
            email VARCHAR NOT NULL,
            code VARCHAR NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMPTZ NOT NULL DEFAULT NOW() + INTERVAL '5 minutes'
        );

        CREATE TABLE "user" (
            id UUID PRIMARY KEY,
            name VARCHAR NOT NULL,
            email VARCHAR NOT NULL,
            hashed_password VARCHAR NOT NULL,
            address VARCHAR,
            role userrole NOT NULL,
            active BOOLEAN NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_user_name UNIQUE (name)
        );
        CREATE UNIQUE INDEX ix_user_email ON "user" (email);

        CREATE TABLE cart (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL UNIQUE REFERENCES "user" (id)
        );

        CREATE SEQUENCE order_number_seq;
        CREATE TABLE "order" (
            id UUID PRIMARY KEY,
            order_number BIGINT NOT NULL UNIQUE,
            total_price NUMERIC(10, 2),
            shipping_address VARCHAR NOT NULL,
            status orderstatus NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            user_id UUID NOT NULL REFERENCES "user" (id)
        );

        CREATE TABLE product (
            id UUID PRIMARY KEY,
            product_name VARCHAR NOT NULL,
            description VARCHAR,
            price NUMERIC(6, 2),
            stock_quantity INTEGER NOT NULL,
            image_url VARCHAR,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            category_id UUID NOT NULL REFERENCES category (id),
            CONSTRAINT check_positive_price CHECK (price > 0),
            CONSTRAINT check_nonnegative_stock_quantity CHECK (stock_quantity >= 0)
        );
        CREATE UNIQUE INDEX ix_product_product_name ON product (product_name);

        CREATE TABLE cart_item (
            id UUID PRIMARY KEY,
            cart_id UUID NOT NULL REFERENCES cart (id),
            product_id UUID NOT NULL REFERENCES product (id),
            quantity INTEGER NOT NULL
        );

        CREATE TABLE order_item (
            id UUID PRIMARY KEY,
            quantity INTEGER NOT NULL,
            unit_price NUMERIC(10, 2),
            is_reviewed BOOLEAN NOT NULL,
            order_id UUID NOT NULL REFERENCES "order" (id),
            product_id UUID NOT NULL REFERENCES product (id),
            CONSTRAINT check_positive_quantity CHECK (quantity > 0),
            CONSTRAINT check_positive_price CHECK (unit_price > 0)
        );

        CREATE TABLE payment (
            id UUID PRIMARY KEY,
            amount NUMERIC(10, 2),
            currency currency NOT NULL,
            payment_status paymentstatus NOT NULL,
            provider_transaction_id VARCHAR NOT NULL,
            payment_method paymentmethod NOT NULL,
            order_id UUID NOT NULL REFERENCES "order" (id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE review (
            id UUID PRIMARY KEY,
            rating INTEGER NOT NULL,
            comment VARCHAR,
            username VARCHAR NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            product_id UUID NOT NULL REFERENCES product (id),
            user_id UUID NOT NULL REFERENCES "user" (id)
        );
    """.split(";"):
        if statement.strip():
            op.execute(statement)


def downgrade() -> None:
    for statement in """
        DROP TABLE review;
        DROP TABLE payment;
        DROP TABLE order_item;
        DROP TABLE cart_item;
        DROP TABLE product;
        DROP TABLE "order";
        DROP SEQUENCE order_number_seq;
        DROP TABLE cart;
        DROP TABLE "user";
        DROP TABLE reset_code;
        DROP TABLE notification;
        DROP TABLE category;
        DROP TYPE paymentmethod;
        DROP TYPE paymentstatus;
        DROP TYPE currency;
        DROP TYPE orderstatus;
        DROP TYPE userrole;
        DROP TYPE notificationtype;
    """.split(";"):
        if statement.strip():
            op.execute(statement)
