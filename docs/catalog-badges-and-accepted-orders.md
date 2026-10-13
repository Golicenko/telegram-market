# Catalogue badges and accepted order cancellation

## Changes

- Existing `content_seen_states` remains the per-user source of truth. `/api/me` and content reads initialize missing baselines to current visible publication revisions. Known bot users who have never opened the Mini App also get a baseline on first Mini App entry.
- Migration `0048_catalog_baseline` resets legacy unseen state for previous Mini App users (or existing seen rows), preserving users, products, orders, balances and history. It locks the two catalogue tables during the short baseline update; rehearse duration on staging. No schema fields added. Downgrade intentionally preserves the corrected baseline.
- First publication allocates a revision; edits, hide/re-publish, purchases and reloads do not allocate another. A PostgreSQL transaction advisory lock serializes publication revision allocation through commit: slower writers cannot publish revision N after N+1 has been acknowledged. Failed transactions cannot create badges.
- Authenticated `GET /api/content/{unique|training}/snapshot` returns `items` and a marker from the same selected rows. Training serialization uses the existing public output schema; admins retain their own draft cards. Client renders a successfully loaded snapshot before acknowledging that exact marker through existing `mark-seen`. Abandoned/failed/hidden/stale requests are not acknowledged. Existing public list APIs are unchanged.
- Existing badge count API checks current published/nondeleted items. Hidden/deleted items do not count. Refresh on foreground and approximately every 15 seconds using the existing polling loop. No localStorage source of truth or new navigation elements.

## Explicit business-rule change requested by owner

Previous policy (including accepted orders refunding after 24h) is superseded by this request:

`paid` (not accepted): participant cancellation remains possible through the existing locked refund service. `seller_contacted` / `seller_accepted_at` means accepted; both participants' cancellation requests receive 409. Legacy `seller_contacted` without timestamp is protected conservatively. Transfer and buyer receipt confirmation modals remain; only buyer receipt or authorized admin resolution settles funds.

At the unchanged 24h delivery deadline, an accepted-but-undelivered order becomes existing `disputed` with `needs_admin_review_at`, one audit event and durable notifications to both participants and admins. No refund, payout, hidden listing or seller penalty occurs in this branch. Existing unaccepted timeout/refund rules are retained. Existing support/evidence and admin resolution flows are reused. No new order status or financial formula. Concurrent acceptance/cancel/timeout serialize on the Deal row; cancelled/completed states cannot be reopened by participants.

## Verification / limitations

New PostgreSQL tests use two distinct validated HMAC test accounts and real API/service/database calls. They cover per-account baseline, draft/publication, captured snapshot versus concurrent publication, hide/republish, restart/new client, direct cancel API, concurrent accept/cancel, accepted timeout review, legacy acceptance and support escrow preservation. Existing full transfer/receipt, duplicate payment, refund and settlement suites remain required. Frontend tests execute snapshot loading, errors, abandoned/hidden screens and superseded responses.

No production accounts, payments, refunds, deployment or migration are executed. Mobile browser regression uses explicit test fixtures, not native Telegram/iPhone/Android E2E. Actual game delivery cannot be verified by automated tests. Existing support requires evidence; admins must monitor their review queue when notifications cannot be delivered.

## Release / rollback

Backup DB, rehearse 0047→0048 on staging, review this changed cancellation policy, then deploy through existing Railway migration command. Avoid mixed old/new backend workers: drain old workers before resuming order processing; an old worker could still refund accepted orders. Code rollback to the old financial policy is NOT safe while accepted orders are waiting for review: pause timeout workers and get owner approval first. Preserve corrected seen baselines. New code can run with old schema because this migration changes only baseline data, but omitting migration retains old false badges.
