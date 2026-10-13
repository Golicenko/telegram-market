# Publication Stars and chat reliability

## Scope / policy

Existing regular Market publication only, shared across CP1/CP2. Defaults: first five lifetime successful publications free, every subsequent new listing costs five **XTR**, not AF. Admin-created products, Unique and training are exempt. Editing, hiding/unhiding, deletion and existing promotion do not use a new slot. Deletion never restores a slot. The optional existing 5 AF pin remains separate; it is charged atomically with publication, not by the XTR receipt handler.

## Data / migration 0049_publication_stars

- `users.publication_count`: atomic lifetime count, locked with the user row during creation. Backfill counts ALL retained regular listings (including sold/paused/soft-deleted), not just active ones. The old creation service immediately published retained listings. Hard-deleted history cannot be reconstructed: the count is a known lower bound, no invented history and no retroactive charges. Verify production retention/backup before rollout.
- `publication_rules`: singleton, free limit, price in Stars, enabled; defaults 5/5/true. Server admin authorization; changes audited with before/after and reason. Price is frozen on each draft, even after changing settings.
- `publication_drafts`: immutable validated listing payload, owner/request identity, original price, reusable invoice, accepted checkout identity/time, unique payment/listing references, durable status/retry/error. No old messages removed.
- `star_payments`: reuse the existing globally unique Telegram charge ID. Publication receipts have `af_coin_amount=0` and a separate status; they never enter AF topup/referral processing or topup metrics. Exceptional extra Telegram charges are retained in a separate admin-refund queue, not silently ignored.
- Chat index `(conversation_id, created_at, id)` for stable bounded cursor pages, including identical timestamps.

Migration takes table locks on users/listings: rehearse on a production-sized staging copy and use a brief write-maintenance window. Do not run mixed old/new publication writers: old code does not enforce the fee/counter. Downgrade deliberately refuses to destroy money evidence. See rollback below.

## Flow

1. Form gets current `/api/publication-rules`, shows remaining free slots or exact Stars fee. The existing pin choice remains independent.
2. `/api/listings` enforces the lifetime counter under a lock; a new regular submission requires a client request ID. Paid requirement is HTTP 402, never bypassed by frontend flags. Competing fifth/sixth requests cannot both take the last free slot.
3. The form persists an owner-scoped draft, confirms the frozen fee in an orange/navy modal and creates/reuses a `createInvoiceLink` invoice through the existing bot client.
4. Verified webhook routes `autoflow_publish:` separately. `pre_checkout_query` validates owner, XTR, exact frozen amount and duplicate checkout. No success based on `openInvoice` callback. Concurrent separate checkout IDs are refused during a 15-minute checkout lease; retries of the same Telegram query are safe.
5. `successful_payment` records the immutable charge before attempting fulfillment. Publication and slot increment are atomic; one payment maps to one request/listing. Wallet/referral credit is never called. Payment receipt survives a publication failure.
6. Frontend polls the server. Closing/cancelling checkout preserves the draft. Reopening the form retrieves drafts from PostgreSQL. Paid drafts retry without another invoice. Recovery worker runs every 60 seconds after restart, with capped backoff; after five failures queues admin review. Pin balance preflight reuses the existing exact-shortfall topup; funds can still change before fulfillment, so receipt recovery remains essential.
7. Admin Listings panel exposes rules, failed paid drafts and exceptional extra charges. Retry and Stars refund require reason/confirmation. A refund intent is durable before calling `refundStarPayment`; restart retries the same charge, and `CHARGE_ALREADY_REFUNDED` recovers a lost response. Published listings cannot use this unpublished-draft refund. Refund and fulfillment lock the same refreshed draft row.

Notifications use the existing persistent outbox, including published/refunded notices and administrative review. Admin must check the queue if bot delivery is unavailable. No production refunds/payments were performed during development.

## API

- GET `/api/publication-rules`; PUT `/api/admin/publication-rules` (reason required).
- GET/POST `/api/publication-drafts`; GET `/api/publication-drafts/{id}`; POST `.../{id}/invoice`, `.../{id}/retry` (owner only).
- GET `/api/admin/publication-drafts`; POST `.../{id}/retry`, `.../{id}/refund` (admin only, reason required).
- GET `/api/admin/publication-extra-payments`; POST `.../{payment_id}/refund` (admin only).
- Existing chat GET `/api/conversations/{id}/messages`: at most 100 messages, `before` OR `after` message ID cursor, ascending response. Cursor must belong to the authorized scope. Existing participants/admin routes and write idempotency remain.

## Chat

Initial tail of 100 messages; older pages preserve position. Polling requests newer messages, reconciles optimistic send IDs and read receipts; no entire-history fetch. Same client ID survives failed/lost-response retry. Incoming messages do not yank a reader to the bottom. Per-chat in-memory text drafts survive keyboard closing/navigation during the current app session (not a new persistent secret store). Read cursor only advances while viewing the bottom; background pages do not mark read. Native selection/Ctrl+C is preserved; long press offers Copy with clipboard fallback. HTML body stays text, not markup.

Composer uses 16px minimum, bounded growing textarea, available visual/Telegram viewport and safe areas; keyboard layout hides auxiliary deal panels while typing (not their actions/state). No `user-scalable=no`. User-controlled zoom is not overridden. Lost connectivity is visible, polling/online recovery loads missed messages. Animations honor reduced motion. Existing transfer/receipt confirmation modals and escrow are unchanged.

## Checks / release gates

Tests include real isolated PostgreSQL with two signed test accounts, fifth-slot concurrency, sixth/seventh payment routing, duplicate receipt, no AF/referral ledger effects, frozen price, failed pin/publication recovery, refund idempotency, cached-row refund race, extra receipt retention, historical backfill, 1000-message cursor pages and unauthorized access. Telegram transport fixtures are **tests only**, not a mock payment mechanism in the app.

Browser tests: 320/360/390/430/960px, two isolated frontend accounts, 1000 messages, older-page scrolling, new-message position, textarea/viewport resize, retry ID, copy/XSS. Publication form tests cover 320/360/390/430px: fee modal, Cancel/Back, persisted draft resume, invoice cancellation, disabled repeat action, and server-only success even after a client `paid` callback. Existing deal confirmation suite covers 320/360/390/430px. Desktop viewport resize is NOT a real iPhone keyboard test.

No new environment variable or bot token is introduced. Use the existing bot configuration and authenticated Telegram webhook; configure the separate staging bot through the existing deployment settings, without reusing production credentials. Quota and Stars price are database-backed admin settings, not frontend constants.

No separate TypeScript typecheck exists (plain JavaScript). Run Node syntax/unit tests, targeted Python Ruff, full PostgreSQL suite, production asset build and generated-asset drift check.

**Not yet verified:** real Telegram test-environment checkout/webhook delivery, native iOS/Android keyboard and clipboard. Owner confirmed a test bot/staging exists; exact connection/location is pending. Do not describe the payment flow as live-verified or release to production before that test.

## Release / rollback

1. Backup, rehearse 0048→0049/backfill; confirm missing historical data policy and admin exemptions.
2. Pause old publication writers and webhook/worker rollout overlap; deploy migration and consistent new code. Validate settings before opening publication.
3. In staging, use the real test bot and two test accounts: fifth/sixth/seventh, cancel, receipt retry, restart after paid-before-published, pin shortfall, refund, then native iOS/Android chat.
4. Watch paid/review/refund_pending queues, bot delivery failures, fee/counter totals. Money changes in production need separate owner approval.
5. Safest rollback: disable new fees in admin while retaining this code to finish already-paid drafts/refunds and immutable prices. Never restore old webhook handling while publication invoices can still settle. Keep new tables/receipts/counters; if reverting UI, retain new payment webhook/recovery handlers until queues are reconciled. Do not roll back the previous PR's accepted-deal protection.

Official references: [Telegram Stars payments](https://core.telegram.org/bots/payments-stars), [Bot API](https://core.telegram.org/bots/api), [Mini App viewport API](https://core.telegram.org/bots/webapps).
