# Seller purchase photo notification repair

## Confirmed code cause

Commit `d3cceb6` (seller acceptance/reminders) moved new purchases to the recipient-scoped `Notification` outbox (`seller_purchase_notification_status="outbox"`). Both purchase paths stored only `deal_id`. The active worker in `message_notifications.send_delivery` always called `sendMessage`. The old `bot.send_deal_purchase_notification` still supported `sendPhoto`, but new purchases deliberately no longer used that legacy sender. This is a code regression; production delivery logs were not provided or inspected.

## Repair and scope

- Retain the existing outbox/claim/retry mechanism. Both direct purchase and legacy cart service add the first `ListingImage` (ordered by position/id) to `Notification.payload.sale_snapshot` in the existing purchase transaction. Title, exact paid price, CP1/CP2 and the existing short order reference are frozen as well. No new numbering policy.
- Caption remains the purchase-time body, bounded for Telegram even with an extremely long Unicode car name. Photo + caption + real `Открыть сделку` inline Web App button are sent in one `sendPhoto`. Same existing `deal_id` routing and backend access checks.
- Resolve relative public upload URLs using existing `PUBLIC_BASE_URL` / Railway public domain; accept absolute HTTP(S) photo URLs and preserve Telegram file IDs. No arbitrary server-side URL downloads. Unsupported schemes, malformed credentials/URLs and missing references use a logged text fallback.
- A definitive Telegram `400` photo rejection permits a single text fallback. Successful fallback marks the same notification `sent` and retains its photo error. Block/rate-limit/config errors keep existing delivery handling. Timeout, invalid response and photo 5xx are ambiguous: no fallback or automatic resend, to avoid delivering both photo and text. Telegram cannot guarantee exactly-once delivery after a lost response; such rows remain `unknown` for review.
- Logs include notification/deal identity, photo-reference hash and Telegram error reason; URLs/query strings and bot tokens are redacted. Errors are outside the purchase transaction, so they never cancel or refund the purchase.
- Pending pre-upgrade rows without snapshots can use their own listing's current first image, then persist it. This cannot reconstruct a previously edited/deleted historical image. Already sent/unknown rows are not replayed. New snapshots with no image stay empty rather than borrowing a later image.

`/api/uploads` normalizes images and stores bytes in PostgreSQL. `/api/media/{id}` is public and immutable, without Telegram initData, so Telegram can fetch it. Editing/deleting listing image associations does not delete these uploaded bytes. Snapshotting a URL cannot prevent deletion of files on an external third-party host; rejection is logged and falls back to text.

## Files / migration / rollback

Runtime: `backend/app/seller_orders.py`, `backend/app/services.py`, `backend/app/message_notifications.py`.

Tests: `backend/tests/test_purchase_photo_notifications.py`, `backend/tests/test_purchase_photo_postgres.py`, existing SQLite fixture `backend/tests/test_chat_lifecycle_db.py` now includes the existing `ListingImage` table.

No schema migration, env addition, new API endpoint, frontend change, escrow/fee/AF/Stars calculation change. Uses existing JSONB notification payload. Rollback code only; retain snapshots and delivery statuses, never reset sent/unknown notifications to pending.

## Verification

- Transport tests: relative/absolute URL, file_id, missing/malformed reference, caption/button/deal URL, explicit failed photo -> text, blocked/rate-limited/ambiguous results, no extra text after timeout, redacted diagnostics, caption length.
- Isolated PostgreSQL + actual HTTP API for CP1 and CP2: upload real test image, three concurrent purchase requests, one order/hold/notification, first photo rather than second/other listing, post-purchase edits/deletion do not change snapshot, anonymous media read, protected deal read, concurrent workers + subsequent worker, successful photo / text fallback / unknown result. Financial state stays paid/held in every notification outcome. Telegram transport is simulated in tests only.
- Legacy pending row recovery; sent notice is not replayed.

Live Telegram delivery and tapping the button on a physical device are NOT confirmed by these tests. Staging bot/URL was previously requested but not supplied. No production messages, purchases, payments, refunds or deployment performed. Before release, use two authorized staging accounts to buy one CP1 and one CP2 car and visually verify the delivered photo and destination deal.

Official API contract: [Telegram sendPhoto](https://core.telegram.org/bots/api#sendphoto) accepts a photo URL/file_id, caption and inline keyboard; the caption limit is 1024 characters.
