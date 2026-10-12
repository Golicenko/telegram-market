# Withdrawal package 2

## Scope and preserved rules

Requests now have immutable customer-facing numbers (#000001, expanding beyond
six digits). UUID remains the technical key. Gift quote calculation, 30% fee,
earned-only reservation, bonus exclusion and manual fulfilment are unchanged.
No Telegram gift/Stars transfer API was added. The admin confirms actual manual
delivery using the existing approval -> paid flow, with an optional reference.

Existing states map to NEW=pending, PROCESSING=approved, PAID=paid; rejected and
cancelled remain. Telegram notification failure is NOT a financial FAILED state.
It cannot reverse payment or release a reservation. Cancellation now has a timestamp.

## Migration 0045

Take and rehearse a database backup first. Migration locks withdrawal_requests,
numbers ALL surviving historical rows (every status) by created_at then UUID,
adds GENERATED ALWAYS identity and UNIQUE, and positions the sequence after the
last historical number. Concurrent inserts wait until migration finishes.
Rolled-back inserts consume numbers: gaps are intentional; numbers are not reused.
Dates/references absent in legacy history remain unknown, not invented. Deleted
historical rows cannot be reconstructed. No production history was inspected here.

SupportTicket gets an optional unique withdrawal FK. Withdrawal gets cancelled_at
and payout_reference. No amounts are recalculated. Downgrade deliberately refuses
to delete public identifiers. On code rollback retain this additive schema/sequence;
old code can still insert and receive generated numbers. Do not reset the sequence.

## API / interface

- WithdrawalOut adds public_number/public_id, reviewed_at/paid_at/cancelled_at and
  payout_reference. POST action accepts optional payout_reference (200 characters).
- GET /api/admin/withdrawals: q=#number, status, limit<=100 (default50), offset,
  or exact withdrawal_id for notifications; admin-only. Search includes old states.
- POST /api/withdrawals/{uuid}/support: owner/admin only; one persisted linked
  ticket, no financial mutation. Reopening keeps the same history.
- GET /api/support/tickets/{uuid}: participant access only; enables user deep links.
- Existing support messages: withdrawal admin replies require client_request_id,
  lock the ticket, and enqueue full text (max3500) atomically with audit/history.
- GET /api/admin/support/tickets supports q matching the public-number topic.

The admin queue has search, status filters, pagination, concise Stars totals,
UTC timestamps and expandable technical detail. Customer history and submission
show the public number. Notification text and completion include that number.
The public SLA is 'Вывод в течение 24 часов', not a measured performance claim.

## Contact and notifications

Admin notice uses the stored quote payout_stars, without a new exchange rate.
It has a real profile link, an exact application request link and 'Связаться через
бота'. Username is validated; fallback tg://user?id depends on Telegram privacy
(https://core.telegram.org/bots/api#inlinekeyboardbutton), not a guaranteed DM.

Contact opens existing support to compose a message. The bot sends the text and
a button to the exact authorized support ticket. The customer replies IN that
Mini App ticket; arbitrary free-form private bot messages are not routed here.
Admin and customer retain a shared thread linked to the withdrawal number.
The queue shows latest contact delivery status including blocked/unknown/failed.
Use refresh after sending. Existing durable outbox retries explicit failures only;
ambiguous timeouts are not blindly resent (Telegram sendMessage has no idempotency
key). No successful financial status is inferred from notification delivery.

## Verification / limits

Regression tests cover 100 concurrent real PostgreSQL reservations, retry of one
quote, concurrent paid commands, stable support association, all-state backfill,
rollback gaps and reopening a DB connection. HTTP tests check owner/admin access,
number search and support notifications. Browser fixture tests cover widths
320/360/390/430, quote/reservation retries and explicit completion confirmation.
SQLite tests have a test-only Identity adapter; they are NOT sequence/race proof.

Run complete backend and frontend suites in CI. No production payments, migration,
messages, withdrawals or deployment are performed. Real privacy behaviour,
physical iOS/Android clients and production delivery still require owner staging QA.
