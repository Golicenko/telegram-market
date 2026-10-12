# Seller progress and reminders — stage 2

## Scope

Continues merged withdrawal PR #63. This package implements seller acceptance,
clear participant progress, immediate paid-order notification and durable reminders.
It does not implement the remaining admin RBAC, analytics, guides, training or VIP redesign.
No production financial operations or production database migration were performed.

## Financial policy confirmed by the owner

- The existing delivery deadline remains **24 hours from purchase**, including when
  the seller has accepted/replied but has not marked transfer. Acceptance does not extend it.
- `paid → seller_contacted → transfer_in_progress → completed` uses existing statuses.
  `seller_contacted` now records explicit acceptance in `seller_accepted_at`.
- Acceptance and marking transfer do not pay the seller. The existing buyer-confirmation
  service performs settlement once; the existing 60-second receipt guard remains.
- Disputes hold funds. The existing 48-hour stale-deal check asks for admin review,
  not automatic settlement. No commission, funding-source or refund calculation changed.
- Existing inactivity sanctions remain unchanged. This package does not introduce new bans.
- Old clients may still mark transfer directly from `paid` after the existing hold/ID/
  status/deadline checks. The new UI guides sellers through acceptance first; this is
  deliberate backward compatibility, not a claim that every historical deal was accepted.

## Backend / API / migration

- Migration `0046_seller_order_progress`, parent `0045_withdrawal_public_numbers`:
  adds nullable `deals.seller_accepted_at` and non-null `seller_reminder_stage` (default 0).
  Historical acceptance timestamps are not invented.
- Extends the existing purchase-notification ownership constraint with `outbox`.
  New purchases use this owner; their true delivery status is in `notifications`.
  Historical `pending/sending/sent/failed` deals continue through the legacy sender.
- Existing authenticated `POST /api/deals/{id}/seller-contacted` now locks the deal,
  validates seller/status/deadline/escrow, records acceptance and queues one buyer notice.
  Replay does not change the timestamp, append another event or send a direct notification.
- `DealOut` adds `seller_accepted_at`. Other API routes are unchanged.
- `seller_order_accepted` and `seller_reminder_queued` events use the existing deal audit.
- Paid-order notification is queued in the purchase transaction, without waiting for
  buyer ID. It shows CP1/CP2, the actual paid AF amount, deadline in UTC and opens the deal.
  ID submission/change produces a separate existing chat-message notification.
- The display order reference is the existing shortened deal UUID, NOT a new sequential
  public order number. Withdrawal public numbering from PR #63 is unchanged.

## Worker and configuration

`SELLER_ORDER_REMINDER_SECONDS=[7200,43200,82800]` defaults to 2h / 12h / 23h after
purchase. Up to three distinct increasing positive offsets below 86400 seconds;
`[]` disables the reminders. Short test offsets are allowed. No new required secret.
Do not reorder a running schedule casually: stages are ordinal and persisted per deal.

The existing periodic seller-timeout worker calls `recover_seller_order_reminders`.
It scans up to 100 due deals per pass. A locked deal advances its stage and queues a
notice atomically. Restart needs no in-process 24-hour sleep. Missed slots coalesce;
older unsent reminders are suppressed at outbox claim time. Acceptance, a real seller chat message, transfer,
dispute or expiry suppress reminders. Viewing the chat is not an acceptance or reply.
Reminder scheduling does not move either existing deadline.

Delivery uses the existing Telegram outbox, including bounded explicit-error retries,
blocked-user handling and `unknown` for ambiguous network results (not blindly resent).
Stale pending reminders are checked again when claimed. A Telegram request already
in flight cannot be recalled if the seller acts at the same instant.

## UI

Reuses the existing deal chat, delivery panel, countdown, support action and accessible
seller/buyer confirmation dialogs. Adds a compact three-step indicator and acceptance CTA.
Buyers see waiting/accepted/transferred/disputed copy, held-funds explanation and the
actual backend deadline. Acceptance never represents successful delivery.
Corrects a pre-existing CSS specificity conflict hiding support buttons; both help and
non-receipt actions are now visible, with at least 44px-high tap targets. Opening the
support form alone does not mutate the order; submitting uses the existing dispute flow.
Fixes the chat listing grid when no photo exists: text no longer occupies the narrow
thumbnail column and pushes the action buttons below the small-screen viewport.

## Verification

- `backend/tests/test_seller_orders_postgres.py`: immediate notification before ID,
  purchase replay, eight simultaneous accepts (including real route/background tasks),
  unchanged escrow/deadline, eight timeout executions with one refund, permission/state
  rejection, reminder restart/concurrency/coalescing/suppression, worker recovery,
  historical migration and schedule validation. Uses disposable PostgreSQL schemas only.
- Existing transfer/receipt PostgreSQL regressions still cover one settlement across
  simultaneous devices; all existing financial tests must remain green.
- `webapp/tests/deal-lifecycle-browser.cjs`: acceptance/reload, seller and buyer modals,
  cancel/Back/Escape/backdrop, ID copy, failed request/retry, double taps and success;
  visible support actions, opening the correct deal's form and Back without mutation.
- `webapp/tests/delivery-deadline-browser.cjs`: CP badges, ID-only submission/reload,
  buyer waiting state, deadline/expiry and admin message retry.
- Browser tests run at 320/360/390/430 CSS px with local API/Telegram SDK fixtures.
  These are not physical iOS/Android Telegram or real payment/delivery tests.
- Frontend is plain JavaScript (no TypeScript project/typecheck target); use Node syntax
  checks, existing Node tests and the production asset build. Backend lint/syntax checks
  supplement the full Linux/PostgreSQL CI suite.

## Release and rollback

1. Back up production DB; rehearse migration on a non-production copy and inspect this diff.
2. Run full CI and local browser tests. Deploy migration before application code. No
   production payment is part of this procedure without separate owner permission.
3. Check worker startup, pending/sent/failed/unknown notices, acceptance and deadlines
   using authorized test accounts. Monitor actual refund/settlement ledger, not UI counters.
4. Disable new reminders with `SELLER_ORDER_REMINDER_SECONDS=[]` if needed. Pending
   outbox messages already queued remain subject to relevance/delivery checks.
5. Migration is additive; keep new columns and ownership values on rollback. Downgrade
   intentionally refuses to erase durable state. Reverting app code to pre-stage-2 stops
   new reminder scheduling, but its outbox lacks new deep-link/staleness handling and its
   legacy ID-update notice does not understand `outbox`. Prefer a reviewed forward fix;
   do not blindly relabel `outbox` to `pending` (could duplicate delivered purchase notices).

Production 30-day metrics, Telegram delivery to real recipients and physical iPhone
keyboard behaviour remain unverified here; this document does not assert they work.
