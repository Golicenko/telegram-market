# Admin operations increment

Continues merged PR #64. No production transactions, deployment or migrations are performed by this change.

## Implemented

- Existing admin page opens an operational overview; tabs load on demand instead of fetching every module at entry.
- `/api/admin/overview`: calendar date window (default Europe/Bratislava), database aggregates, current queues, explicit metric definitions. Completed/cancelled are timestamped transitions; created-order status buckets are a cohort's CURRENT state, not a reconstructed funnel. Confirmed Stars credits come only from `star_payments.status=credited`, not invoices. Pending queues are explicitly all-time/current.
- Missing historical DAU, sessions and screen views are null/unavailable, never fabricated zeros. No claim to diagnose a production conversion drop without telemetry/log access.
- `/api/admin/audit`: bounded, stable pages, actor/target/action filters. Existing audit records, actor, timestamp, reason, allowlisted before/after fields only. Historical missing reasons remain missing; arbitrary metadata/payment payloads are not exposed.
- `/api/me.admin_access`: server-derived capabilities. Owner = ADMIN_ID; existing administrators unchanged; SUPPORT_TELEGRAM_IDS (JSON array, e.g. `[123,456]`) grants only support queue/read/reply/status permissions. Support remains `User.role=user`, so existing financial/creation privileges cannot accidentally be inherited. Role membership is configuration-managed, not editable by users or via new unsafe role APIs.
- Every existing admin financial command remains `require_admin`; support cannot withdraw, refund, complete, adjust balances, manage users/listings/training or broadcast. Support may communicate in an existing deal through its support ticket, using the existing transactional message/outbox function. Replies are audited.
- User search supports name/surname/username/Telegram ID/internal UUID, escaped search wildcards, bounded pages; removes per-user wallet/count round trips. Listings/deals gain bounded pages and server status filters. UI includes paging and debounced user search, failure/retry, and hides privileged tabs for support.

## Compatibility / migration

No new tables or migrations; existing routes/response list shapes retained. `me` gains one additive field. Main addition is `backend/app/admin_operations.py`, `admin_access.py`, `webapp/js/admin-operations.js`; app/main/routes/schema/config/build/style integrate them.

No financial rates, escrow, settlement, refund, withdrawal calculations or 24/48h deadlines changed. ADMIN_ID/ADMIN_TELEGRAM_IDS continue working. SUPPORT_TELEGRAM_IDS is optional and empty by default; configuring it requires a normal deploy. Keep ownership/admin environment access restricted. This is conservative RBAC, not delegated role management.

## Verification and demonstration

- `test_admin_operations.py`: role capabilities, blocked staff, DST (23/25h days), invalid periods, every admin route rejects ordinary users and all non-support routes reject support before database access. Isolated PostgreSQL report/payment/audit/pagination/support tests.
- `node webapp/tests/admin-operations-browser.cjs`: explicit fixtures with external HTTPS blocked; admin/support at 320/360/390/430; lazy loading, pagination, hidden capabilities, overflow, JS errors, local screenshots. These are not production or native Telegram tests.
- Existing backend financial suite and frontend regression suite must remain green. Build: `python backend/scripts/build_webapp.py`.
- Demo: admin → Overview → date range → Users (search, page) → Audit; support → only Support. API attempts from support to financial routes must return 403.

## Known remaining scope (not claimed complete)

Full historical analytics/funnels require event instrumentation and retention policy; real production 30-day logs/DB counts remain unverified. Editable guide CMS/onboarding needs real screenshots. Remaining training funnel, VIP design and wallet/iOS device work are separate increments. This is not completion of the entire nine-stage programme. Existing administrative operations lacking mandatory reasons/complete before-after history need further targeted remediation; this journal does not manufacture their missing history. Public order numbers, role delegation and settings editor are not introduced here.

## Release / rollback

Review tests against disposable PostgreSQL; deploy code only after CI passes and owner approves. No schema migration required. Smoke-test `/me`, denied user/support financial requests, admin report, existing deal/withdrawal controls. Roll back code to previous image if necessary; financial rows are unchanged. Remove SUPPORT_TELEGRAM_IDS to revoke support membership immediately after restart. Do not backfill analytics from invented assumptions.
