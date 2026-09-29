# Vee e-commerce API

FastAPI with asyncpg services and explicit PostgreSQL migrations. Run the API
with `uv run python main.py`; interactive API documentation is at
[localhost:8084/docs](http://localhost:8084/docs).

## Orders, reviews, and reports

All bodies accept camelCase and snake_case fields. Responses use the existing
`{status_code, message, data}` envelope and camelCase resource fields. Protected
routes require `Authorization: Bearer <access-token>`. List routes default to
`limit=50&offset=0`, with a maximum limit of 100.

| Method | Endpoint | Access and behavior |
| --- | --- | --- |
| POST | `/api/orders/checkout` | Authenticated user's cart; creates a pending order |
| GET | `/api/orders` | Customers see their own orders; admin/delivery see all |
| GET | `/api/orders/{order_number}` | Same ownership rule as the list |
| PATCH | `/api/orders/{order_number}/status` | Status transitions governed by role |
| GET | `/api/reviews?productId={uuid}` | Public, paginated product reviews |
| POST | `/api/reviews` | Delivered purchase required; one review per user/product |
| PATCH | `/api/reviews/{review_id}` | Owner may change rating, comment, or both |
| DELETE | `/api/reviews/{review_id}` | Owner or admin; returns an empty 204 response |
| POST | `/api/reports` | Report exactly one product or review |
| GET | `/api/reports` | User's reports; admin sees all; optional `status` filter |
| GET | `/api/reports/{report_id}` | Reporter or admin |
| PATCH | `/api/reports/{report_id}` | Admin resolves or dismisses an open report |
| GET | `/api/reports/sales` | Admin sales and order analytics |

Order identifiers in paths are the positive human-readable order number.
Review and report identifiers are UUIDs returned by their APIs. Order items also
include product UUIDs, which clients can use when submitting reviews or reports.

Checkout accepts:

```json
{"shippingAddress": "12 Example Street, Cairo"}
```

The server calculates totals from current catalog prices, snapshots names and
prices into order items, reserves stock, and clears the cart in one transaction.
It locks the user, cart, and products to serialize conflicting operations.
Insufficient stock returns 409 and preserves the cart; an empty cart returns 400.
The same cart cannot be checked out twice concurrently. A fresh cart may create
another order; there is no cross-cart request idempotency key yet.

Order status requests accept:

```json
{"status": "processing"}
```

Admin transitions are `pending -> processing -> shipped -> delivered`;
`pending` and `processing` may also transition to `cancelled`. Customers may
cancel only their own pending orders. Delivery staff may advance processing
orders to shipped, then shipped orders to delivered. Completed and cancelled
orders are terminal. Repeating the current status is idempotent within these
role permissions. Invalid transitions return 409; forbidden actions return 403.
Cancellation restores reserved stock exactly once and cancels pending payments.
An order with a completed payment requires a recorded refund first; these routes
do not process payments or issue refunds.

Confirmation and status emails run as best-effort background tasks after the
order transaction commits. SMTP errors are logged and cannot undo checkout.
Delivery is not durable across process crashes; a production deployment that
requires reliable email should add a transactional outbox and retry worker.

Review creation accepts:

```json
{"productId": "<product UUID>", "rating": 5, "comment": "Great product"}
```

Ratings must be 1-5. Reviews require at least one delivered order containing the
product. Duplicate reviews return 409. Updating or deleting another user's
review returns 404, except admins may delete reviews. Creating/deleting reviews
also updates the user's order-item `isReviewed` flags. Reviews are editable with
partial PATCH bodies; empty bodies and explicit nulls are rejected.

Customer reports accept exactly one target:

```json
{"reviewId": "<review UUID>", "reason": "Spam or misleading content"}
```

Use `productId` instead to report a product. One open report per reporter/target
is allowed; duplicates return 409. Admin moderation accepts:

```json
{"status": "resolved", "resolution": "Removed the reported spam review"}
```

Use `dismissed` to reject a report. Moderation requires a written resolution.
Closing a report does not automatically remove the target; review deletion is a
separate admin action. Closed reports cannot be changed; repeating the same
resolution is idempotent. Reports survive review deletion with `reviewId=null`
and `targetType=review`, preserving the reason and moderation history.

The sales endpoint accepts optional timezone-aware `start` and `end` timestamps:

```text
/api/reports/sales?start=2026-09-01T00:00:00Z&end=2026-10-01T00:00:00Z
```

The range includes `start` and excludes `end`, filtering by order creation time.
It returns total orders, counts and order values for all five statuses, delivered
sales, average delivered order value, and the top 10 products by delivered sales.
A repeatable-read snapshot keeps its sections consistent. Delivered sales are
order values, not collected payments or net revenue after refunds. The catalog
currently has no currency field; analytics assume a single catalog currency.

Public registration creates customer accounts only. Administrator and delivery
accounts must be provisioned through a trusted administrative process.

## Database upgrades and validation

Apply migrations before using the new routes:

```powershell
uv run alembic upgrade head
```

The new migrations backfill purchased product names from the current catalog,
add review uniqueness/rating constraints and indexes, and create customer
reports. Historical product names cannot be recovered if they were already
changed before this upgrade. Existing duplicate reviews or ratings outside 1-5
must be corrected before upgrading; the migration deliberately preserves data
and fails rather than deleting feedback. Test upgrades on a disposable database.

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Database tests skip unless `TEST_DATABASE_URL` is set to a disposable PostgreSQL
DSN. They apply the migration SQL in randomly named temporary schemas and remove
those schemas afterward. They cover checkout rollback, stock races, repeated
cancellation, ownership, review races, reporting, and migration downgrade/upgrade.
HTTP and email tests use mocked integrations and never send real email.
