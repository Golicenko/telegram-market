# Marketplace delivery update

## Scope

- CP1/CP2 badges sit inside the photo at top-left: translucent amber / blue,
  readable light text. The existing unique label moves to the photo bottom-left
  to avoid overlapping; it is not placed over the purchase button.
- Buyer submits only `buyer_game_id` (text, 1–128 characters; letters/case preserved).
  Server/time inputs and their notification copy are removed. Historical database
  fields are retained, not cleared or dropped.
- Seller sees a prominent hours/minutes countdown above the chat. The frontend
  displays a PostgreSQL deadline and never performs a refund itself.
- Admin can send a message to both participants separately from internal notes,
  and refresh the conversation. Network failure preserves the draft and request ID.

## Deadline and financial safety

Migration `0041_seller_delivery_deadline` follows `0040_listing_game_version`.
It adds nullable `deals.seller_delivery_deadline` (timestamptz) and its index.
Existing paid/contacted/disputed deals without a transfer receive a full 24-hour
grace period from migration time; deploying does not instantly refund old orders.
No users, listings, old delivery data, purchases, messages, or balances are deleted.

New purchases store now + 24 hours in the same transaction as their existing hold.
Changing the ID or sending messages does not extend that deadline. It is distinct
from the old seller-response/inactivity deadline, whose separate policy remains.

The existing worker scans durable deadlines every configured polling interval
(default 5 seconds). It first checks the existing inactivity case, then checks
untransferred purchases. Expiry re-locks the deal, listing and wallet, rechecks
reservation/status/hold components, and calls the existing `_apply_deal_refund`.
Refund ledger entry, cancellation, chat closure, and both notification records
commit together. Replays see a cancelled deal and do nothing.

The new reason is `delivery_timeout`; the affected listing is paused, not deleted.
The new transfer-timeout path does not hide unrelated listings. Existing inactivity
sanctions remain in the existing handler. Transferred, completed, cancelled and
disputed deals are not auto-refunded by this new timer. After the seller marks
transfer, existing buyer confirmation/dispute procedures apply. An explicit admin
resume of an untransferred dispute grants a fresh 24 hours, matching the existing
resume policy; ordinary activity never does.

## API and admin messaging

- `PUT /api/deals/{id}/delivery-details`: only `buyer_game_id` is required.
  Older clients' extra server/time values are ignored.
- `DealOut`: includes `seller_delivery_deadline`.
- `POST /api/admin/deals/{id}/messages`: admin-only; `body` and UUID
  `client_message_id` required. Active/disputed deal only.
- Existing admin control GET still returns both participants' messages.
- Admin replies through a deal's support ticket reuse the same helper.

Admin messages reuse `ConversationMessage` (system styling with explicit admin
attribution). Deal row locking plus existing client-message uniqueness makes
retries idempotent. A persisted `admin_joined` audit event avoids repeating the
first-join wording for every message. Both participants receive separate durable
`deal_admin_message` outbox entries with the exact `deal_id` link, even if one
participant has already read the message. Internal comments stay internal.
Subsequent actual admin messages get a short new-message notice.

The existing outbox delivers these after commit; uncertain Telegram sends are not
blindly replayed. Telegram receipt cannot be guaranteed if a user blocks the bot.
The seller purchase-notification worker now excludes closed deals and missing IDs.

## Changed files

- `backend/app/models.py`, `schemas.py`: persisted deadline and ID-only contract.
- `backend/app/services.py`, `deal_lifecycle.py`: deadline, existing refund reuse,
  admin chat and idempotency.
- `backend/app/routes.py`: APIs, worker recovery, support-message reuse.
- `backend/app/bot.py`, `message_notifications.py`: ID-only copy, explicit admin notices.
- `backend/migrations/versions/0041_seller_delivery_deadline.py`.
- `webapp/js/app.js`, `webapp/css/style.css`: scoped UI changes.
- `backend/tests/test_deal_delivery_flow.py`,
  `backend/tests/test_delivery_deadline_admin_chat.py`.
- `webapp/tests/deal-delivery-flow.test.cjs`,
  `webapp/tests/delivery-deadline-browser.cjs`.

## Verification

- Backend pytest suite; new persistence/HTTP tests cover ID-only data, restart,
  immutable deadline, full refund once, transaction rollback, worker recovery,
  transferred/disputed exclusions, late transfer rejection, admin role and closed
  chat checks, message replay, notices for both sides, support reply and admin resume.
- Frontend Node test suite.
- `delivery-deadline-browser.cjs`: mobile Chromium at 320/360/390/430, CP1/CP2
  badge positioning, ID-only submission/double tap/reload, keyboard-sized viewport,
  full ID copy, countdown/expiry, admin draft recovery/request ID reuse.
- Existing `deal-lifecycle-browser.cjs` at all four widths.
- Existing `listing-game-version-browser.cjs` at 390.
- Alembic PostgreSQL offline SQL generation for 0040 → head; diff whitespace check.

Limitations: the database fixture uses SQLite, not PostgreSQL concurrency; browser
checks use a mocked Telegram SDK/API, not native keyboards. Real iPhone/Android
Telegram, live bot delivery, and Railway migration/restart are not available here.
Before production rollout, apply migration on staging PostgreSQL and verify one
purchase with two Telegram accounts, actual notifications/deep links, native
keyboard behavior, and competing transfer/refund requests.
