# Audit remediation — staged delivery

This is an existing production application. No production payments, refunds,
withdrawals or database migrations are performed by these development tests.

## Stage 1: audited transaction defects

- Administrative balance adjustment requires a client UUID `request_id`.
  The client blocks concurrent submits before the confirmation dialog, retains
  the key for a retry after a lost response, and clears it after success.
- The server serializes commands per administrator, checks the complete payload
  on replay, and records one adjustment/ledger/audit entry. A reused key with a
  different target, amount or reason returns 409. Missing keys return 422;
  non-admins return 403. New deliberate operations use new UUIDs.
- Buyer game ID is immutable after the seller marks the car transferred. No
  notification or state mutation occurs for a rejected edit.
- Settlement, participant refunds, deadline refunds and administrative dispute
  resolution use Listing -> Deal row-lock order, matching purchase retries.
- Sale commission, gift withdrawal calculation, bonus provenance and the
  existing buyer confirmation / 60-second check are unchanged.

### Migration and API

`0044_admin_balance_idempotency` adds nullable historical `request_id` and
UNIQUE(admin_id, request_id) to `admin_balance_adjustments`. Historical rows and
all wallet/ledger amounts remain unchanged. The HTTP request schema makes the
new key mandatory for new commands. Endpoint paths do not change:

- POST `/api/admin/balance-adjustments`
- POST `/api/deals/{id}/delivery-details`
- existing purchase/confirmation/refund endpoints

This does not make different UUIDs for two separately confirmed manual commands
the same command. Losing client state/reloading after an ambiguous response still
requires checking financial history before intentionally issuing a new command.

### Verification

New regression suites: `test_audit_financial_safety.py` and
`test_audit_financial_postgres.py`. They cover credit/debit replay, changed payload,
permissions, missing key, immutable recipient ID, ten concurrent balance calls,
purchase retry overlapping settlement/refund, and migration of an actual
historical adjustment. PostgreSQL tests create/drop only isolated test schemas.

`.github/workflows/financial-safety.yml` runs the complete backend suite with
PostgreSQL 17 / Python 3.12, frontend tests and deterministic frontend build.
Local Windows currently blocks the installed asyncpg native DLL by application
control policy; this is not bypassed. CI is the full PostgreSQL release gate.

### Release and rollback

1. Obtain DB backup and verify restore on a separate database.
2. Pass CI and review financial diff. Production metrics/30-day logs still need
   authorized read-only access; passing tests does not establish those figures.
3. Pause manual balance adjustments during rolling deployment. Apply additive
   migration, deploy backend/frontend together, and refresh cached clients.
4. Verify an authenticated non-financial smoke test and migration revision.
   Real transactions require the owner's explicit approval.
5. On incident prefer a forward fix. Keep the additive migration on code rollback:
   dropping request identities reopens replay risk. Do not restore an older
   unprotected adjustment endpoint unless that endpoint is disabled server-side
   or the idempotency fix is backported. Never reverse ledger entries by deleting
   history or blindly restoring an old production database over newer payments.

## Remaining requested stages (not claimed complete by this PR)

1. Withdrawal public sequence/backfill, short notices and reliable contact fallback.
2. Seller acceptance, reminders, agreed response/transfer SLA and review rules.
   Current purchase+24h delivery and buyer-action+24h response deadlines differ;
   do not silently change them. Keep two-party confirmation and dispute safety.
3. Admin pagination/search/overview and owner/admin/support RBAC with server audit.
4. Authoritative monetary analytics plus client funnels and timezone reporting.
5. Editable guides/onboarding and real owner-approved screenshots, no mock screens.
6. Training delivery recovery, failure visibility, refund/fulfilment policy and funnel.
   Automatic training currently settles before Telegram delivery; changing that
   financial policy needs an explicit agreed design and migration review.
7. iOS input font/keyboard checks and clearer topup/withdraw UX without rate changes.
8. Existing VIP visual/state improvements, expiration and sorting tests.
9. Final staging/security/production-readiness gate, including physical Telegram
   clients, backups, blocked-bot delivery and authorized payment smoke tests.

The implementation order follows financial safety first. Neither this PR nor its
test totals represent completion of all nine larger product tasks.
