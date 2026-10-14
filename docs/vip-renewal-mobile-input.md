# Part 2: VIP renewal and mobile input

## Scope and causes

Built on merged PR #71, without changing purchase/escrow/withdrawal/referral economics.

Two concrete causes of the buyer game-ID bug were found in `webapp/js/app.js` and `webapp/css/style.css`:

1. `renderConversation()` calls `renderDealDeliveryPanel()` on incoming messages/read changes. The latter unconditionally detached the form. This discarded the typed ID, selection, IME composition and keyboard focus.
2. The `body.chat-keyboard-open .deal-delivery` rule hid the complete ID form as soon as the keyboard was detected. The detector also used physical screen height, not the Mini App's resting viewport.

The existing form now survives updates for the same deal while details are required. Drafts are scoped to the deal in memory and cleared after save. ID remains a string, including leading zeroes and letters; backend's existing trimmed 1–128-character validation is unchanged for CP1/CP2. No automatic synthetic focus, numeric conversion, touch interception or keyboard-hiding API was added.

One shared viewport calculation feeds chat and keyboard-open dialogs. visualViewport and Telegram viewport events use the current visible height, with resting/stable height used only to detect keyboard shrinkage. Focus moving from input to Submit does **not** reset the layout before the click. Explicit pinch zoom is respected. Text inputs/textarea/select use at least 16 CSS px. Dialogs can scroll within safe areas. Chat drafts survive resizing. Message scroll is restored synchronously rather than in a frame racing user scroll.

There is no separate editable profile form in the current product: profile data refreshes from Telegram. No new profile editor was invented.

## VIP display and expiry

All effective `pinned && pinned_until > now` car cards use the same new CSS, including pins purchased before this release. Thin gold edge, small upper-left VIP badge, separate readable CP1/CP2 badge below it, short occasional edge sheen; reduced-motion disables sheen. No old periods, prices, owners or listing descriptions are rewritten.

The existing server serialization/filtering removes expired priority. Existing UI expiry logic removes the decoration without deleting the listing. The old read-path cleanup in `routes.expire_promotions()` also erased `pinned_until`; that would lose the event before a background worker saw it. It now clears only `pinned`. The promotion worker creates `VipExpiry` for each expired `(listing_id, pinned_until)`. Row locks/skip-locked plus a UNIQUE constraint serialize multiple workers. Clearing `pinned` does not clear `pinned_until`, change listing status, or invoke ordinary listing-expiration rules. Dates already erased by older production versions are not invented or reconstructed by this migration.

Only still-active, non-deleted listings receive offers. Existing expired eligible pins are processed in bounded batches of 100 on the worker's existing 30-second loop. This may send offers for eligible pre-release expiries; the notification flag can disable that rollout. No financial debit occurs at expiry.

The expiry row and a pending notification commit together. The existing Telegram outbox sends the exact car name and a real **Продлить VIP** WebApp inline button targeting `?vip_renewal=<offer UUID>`. No photo is required for this optional-photo notification. The generic outbox suppresses stale offers, serializes delivery per recipient, and never replays an ambiguous send. **Telegram has no sendMessage idempotency key**: on timeout/interrupted send, delivery is marked unknown for audit, not blindly repeated. Exactly one durable event is guaranteed, not unconditional delivery to a blocked/offline Telegram recipient.

## Renewal and payments

New authenticated `GET /api/vip/renewals/{renewal_id}` returns actual owner-authorized listing/title, tariff and wallet split. Existing `POST /api/vip/orders` accepts optional `renewal_id` with `listing_id`; other existing order/status/cancel endpoints remain unchanged.

Ownership, active/not-deleted listing, expired current period, no active VIP, unused offer and matching exact period are server-checked. Repeated client request IDs are idempotent. A reused invitation after a later renewal period is rejected. Foreign/sold/deleted cars cannot start payment. Pre-checkout checks again; if availability changes after a genuine receipt, the existing recovery path restores AF instead of pinning an unavailable car.

Defaults: **10 Stars / 72 hours**. Tariff is snapshotted into the invitation and payment order. The current top-up implementation credits **1 purchased AF per confirmed XTR**; no new exchange rate is introduced. Balance 4 AF means reserve 4 AF and invoice 6 Stars. Full AF and full Stars use the same existing order pipeline. Fractional balances retain the existing rounding-credit rule. Cancel/expiry releases the hold in its original purchased/earned/bonus provenance. Final consumption and pin activation commit atomically only after the required receipt. Confirmed late receipts and failed fulfillment follow PR #71's documented AF restoration, not an invented automatic Stars refund.

`ListingPromotion.renewal_id` links the payment to the offer. Redemption timestamp, final ledger, exact new `pinned_until = now + duration_hours`, completion notification and paid order commit together. Restart/retry does not extend the period or consume money twice. Normal pin tariff, publication fee, commissions and balance rules are unchanged.

The renewal dialog reuses `purchaseModal`, native dialog/backdrop, existing toast, `openInvoice`, AF formatting and API authorization. It has a separate gold presentation, actual car title, full tariff, AF reservation and exact Stars remainder. Opening the link creates **no invoice**; only explicit confirmation does. Closing/cancelling follows the existing durable reservation cancellation. Success is based on server order completion, not the Telegram frontend callback.

## Schema/config/files

- Migration `0051_vip_expiries` (after `0050_listing_promotions`): `vip_expiries`, unique listing/expiry period, positive tariff check; nullable FK `listing_promotions.renewal_id`; partial eligible-expiry index on listings. No destructive backfill or financial rewrite.
- `backend/app/models.py`, `promotions.py`, `message_notifications.py`, `routes.py`: offer/state/payment/outbox integration and preservation of the exact expiry date.
- `backend/app/config.py`, `backend/.env.example`: `VIP_RENEWAL_PRICE_STARS=10`, `VIP_RENEWAL_HOURS=72`, `VIP_EXPIRY_NOTIFICATIONS_ENABLED=true`. No additional token, domain, worker service or parallel admin-settings subsystem needed. Existing bot token/public WebApp URL and Telegram authorization are reused.
- `webapp/js/app.js`, `webapp/css/style.css`, stamped `webapp/index.html`: stable ID/chat/viewport and VIP styling/renewal routing.
- Backend tests: `test_vip_renewal_postgres.py`, `test_vip_renewal_notifications.py`.
- Browser regression: `webapp/tests/vip-renewal-keyboard-browser.cjs`; existing source-contract tests updated to describe the shared input viewport and preserved ID form.
- Existing financial-safety CI now runs the isolated renewal/keyboard browser regression as well.

## Verification (not live production)

- PostgreSQL 17 CI: **584 backend tests passed**, **105 JS tests passed**, the four-width browser regression and production static build/hash check passed: https://github.com/Golicenko/telegram-market/actions/runs/38641553060 . Latest tested HEAD is also linked in the PR checks below.
- PostgreSQL scenarios: legacy expiry once across concurrent workers/restart; active legacy pin not rewritten by migration; CP1/CP2; AF balance 0/4/10/20; duplicate receipt/fulfillment; 72-hour expiry; fresh offer for new period; old/foreign/sold/deleted offer rejection; unavailable at pre-checkout/after receipt; restoration/cancel/retry; outbox claim/stale suppression; configurable duration/notification toggle.
- Real DOM in local headless Edge, API/Telegram **test fixtures only**: 320/360/390/430 px, Telegram safe-area fixtures. ID input focus, retained DOM node/selection during polling, simulated keyboard at 350 px, leading zeroes/letters, empty ID blocked, 128-character ID and deletion, simulated paste/input, network failure/retry, double submit, chat draft across repeated resize, all static text-control computed fonts >=16, no zoom restriction, renewal deep link/cancel/confirmed server success, existing VIP badge and expiry, reduced-motion and no horizontal overflow.
- Existing browser suites passed: two-account chat with 1,000 messages at 320/360/390/430/960; seller/buyer confirmations at 320/360/390/430; training/standard VIP at four widths; compact navigation/top-up at four widths; support at four widths; manual withdrawal at four widths; CP1/CP2 create/upload/edit/reopen/detail at 390.
- No TypeScript toolchain exists; JS syntax checks + node tests are used, not a claimed TypeScript typecheck. Ruff checks changed Python files.
- Screenshots are **isolated fixtures**, not actual users/production orders. `webapp/tests/vip-renewal-modal-*.png` and `vip-renewal-*.png` record the layout.

**Not verified:** physical iPhone/Android Telegram keyboards, native clipboard permission on those devices, live bot notification delivery and real staging Stars checkout. No staging URL/test bot configuration was supplied; @Lunoj was identified as a personal account, not a test bot. No real production payment, debit, refund, payout or bot message was performed.

## Release and rollback

1. Back up production DB using the existing operational procedure; owner/operator must do this before deployment. Test migration in disposable PostgreSQL first.
2. Apply additive migration then deploy matching backend/frontend asset version. Keep existing promotion and notification workers running.
3. Optionally begin with `VIP_EXPIRY_NOTIFICATIONS_ENABLED=false` while validating staging. Disabled periods are recorded without queuing messages; enabling later is not an automatic historical resend.
4. On staging, use two authorized test accounts: expired owner offer → native bot button → 4 AF + 6 Stars → one receipt/ledger → pin 72h. Repeat cancel, duplicate callback, sold listing and next-period expiry. On actual iOS/Android check typing/paste and multiple keyboard openings for ID, description, chat and monetary inputs.
5. Monitor pending/paid/restored promotion orders and pending/unknown/blocked notification delivery states. Never label a payment complete from a frontend animation alone.
6. Emergency stop for new expiry notifications is the config flag. For application rollback, retain schema and all financial evidence, drain or preserve a compatible worker for paid/pending renewal orders and queued renewal notifications. Do not downgrade/drop the offer table or restore a stale DB snapshot over real transactions. Old code lacks the renewal link handler, so rolling it back with outstanding invitations requires keeping the compatible route/outbox or explicitly coordinating the queue first.

Latest CI results: https://github.com/Golicenko/telegram-market/pull/72/checks . The PR description records the final tested commit/run; an earlier green run is not treated as proof for later untested changes.
