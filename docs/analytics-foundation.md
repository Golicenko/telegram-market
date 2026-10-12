# Analytics foundation (after PR #65)

## Delivered

- Authenticated `POST /api/analytics/events`: only allowlisted UI observations, UUID identity, 30-second semantic deduplication (one Mini App launch per document/session), per-user database lock and 120/hour cap across replicas. Financial event names, arbitrary text, extra fields and user IDs are rejected. Server UTC timestamps; enums for platform/source/failure reason; optional product UUID only. No message text, raw errors, payment payloads, tokens or Telegram IDs in the observation table.
- UI instrumentation for document launch, market/training list, listing/training detail, buy/checkout, top-up screen, explicit checkout errors and support. Hidden pages and staff browsing do not send UI observations. Errors are isolated from commerce: no waiting for telemetry, no payment retry, no error toast, 60-second circuit pause. No localStorage payload queue. Device/source fields are client observations, not trusted payment evidence.
- `GET /api/admin/analytics`: authoritative monetary projections from existing ledger, Stars payments, withdrawal, referral and training records. No new settlement/refund/payment calls and no duplicated financial event store. Includes previous equal LOCAL-calendar period, explicit seller acceptance mean/median/p90 and cohort-based top-up/detail-view-to-training-payment counts. DAU is distinct authenticated users with observed Mini App activity per local date; launches are document opens, not every request or bot start. Account creation is kept separate from launches.
- `GET /api/admin/analytics/training`: bounded product pages, views/viewers, real purchases, current fulfilment/delivery failures for purchases in the selected date range. These independent totals are not presented as a cohort conversion percentage.
- Existing admin panel gains Analytics tab with date controls, server comparison table, cohorts, daily activity, client failure/platform breakdown, seller acceptance timing and product report. Support and ordinary users cannot access either report.

## Migration / config

`0047_analytics_observations` adds only `analytics_events` and singleton `analytics_state`, with indexed timestamps/user/name and unique user/dedup key. It records collection start, never invents old observations or changes wallets. Old financial data remains in its original tables.

Optional `ANALYTICS_ENABLED=true` (default); `ANALYTICS_RETENTION_DAYS=180` (7..365). Hourly restart-safe cleanup deletes at most 10,000 expired **observation** rows per run; never financial history. Retained-from watermark makes older periods unavailable/partial. While disabled, reports show client metrics unavailable; cleanup advances the watermark to conservatively exclude the paused interval. Sparse/no observations do not prove absence of users when collection/network was unavailable.

## Definitions / limits

- Server `topup_success` is `star_payments.status=credited`, not a frontend invoice callback. One unique charge record contributes once. `topup_checkout_started` includes all persisted Stars intent purposes, not merely the wallet screen. UI failure reasons describe client outcomes and do NOT prove payment failure; successful_payment remains authoritative.
- Top-up cohort: users who opened the top-up screen in measured interval → subsequently created an invoice before period end → a credited payment referencing that invoice before period end. Shortfall flows that do not visit that screen are outside this cohort but remain in server payment totals. Telemetry is best effort; delayed/missing observations can undercount cohorts.
- Training cohort: distinct user/product detail viewers → actual later purchase of that product before period end. Direct catalog purchases without detail view are outside this cohort but remain in paid totals. Fulfilment report is current state, not a historical fulfilment-transition count.
- Ledger order amounts: `protection_hold` = held AF; `sale_income` = actual seller payout; refund/dispute_refund = returned AF. Counts reflect preserved ledger history; cannot reconstruct deleted historical records. Legacy paid withdrawals without stored Stars amount display unknown, not an invented rate or zero.
- Referral milestone/commission data comes from immutable reward records. No changes to new-user-only qualification or bonus withdrawability. Paid pins are ledger promotion operations; free admin pins are not falsely counted as paid.
- Seller response timing measures explicit acceptance (`seller_accepted_at - created_at`) for accepted orders, not chat response time. Unaccepted orders are not zeros. CP1/CP2 segmentation, new/experienced seller segmentation, ordered multistep training checkout cohort, repeat-purchase dashboard and experiment statistics are not yet provided by this increment.
- No production 30-day numbers or real Telegram/device behaviour claimed. Historical UI funnels do not exist before migration. No fake screenshots/data are installed; browser fixtures are tests only.

## Checks / release

Tests cover spoofed financial events, privacy schema, parallel dedup/replays, collisions, throttling, retention isolation, additive migration, replayed real test payment/training purchase projected once, cohort joins and staff report access. Browser fixture QA: admin/support 320/360/390/430 px; frontend tracking failures must not affect actions. Existing financial suite remains release gate.

Deploy: owner backup → rehearse upgrade from 0046 on staging → apply additive migration through existing deployment mechanism → deploy code → verify authenticated events and admin report. Do not run a real Stars charge without owner approval. Rollback: previous image; keep the additive tables. Set ANALYTICS_ENABLED=false to stop observation ingestion. Downgrade deliberately refuses deletion of collected data. No production migration/deploy executed by development tools.
