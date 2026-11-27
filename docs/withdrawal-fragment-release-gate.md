# Manual Fragment withdrawals: release gate

The existing fee remains 30%. Only earned/withdrawable AF is reserved; purchased
and referral/bonus funds cannot be withdrawn. Gross reserve is
`ceil(net Stars / 0.70, 0.01 AF)` and the unused part of the budget stays available.
The commission is part of the reserve, never charged a second time.

## Default: preserve the existing gift payout policy

`FRAGMENT_WITHDRAWALS_ENABLED=false` is the default. With this setting the current
gift denomination calculator and existing configured gift payout ceiling remain
unchanged. This is intentional: do not promise unsupported external quantities.

## Before enabling

On 2026-11-27 the official Fragment Stars purchase and About pages returned HTTP
403 to the audit browser. Official Telegram documentation confirms the Fragment
purchase option, but does **not** establish the currently supported minimum,
maximum, arbitrary quantities or recipient eligibility:

- https://fragment.com/stars/buy
- https://core.telegram.org/api/stars

Third-party claims are not verification. An owner must check the live official
Fragment UI without executing a production payment. Confirm at least quantities
51, 52, 53, 77, 123, 567 and 1250, recipient requirements and regional/account
restrictions. Record evidence/date and set the verified interval:

- `FRAGMENT_WITHDRAWAL_MIN_STARS` (default 51; cannot be below 51)
- `FRAGMENT_WITHDRAWAL_MAX_STARS` (default 1000000)
- `FRAGMENT_WITHDRAWALS_ENABLED=true` **only after that verification**

The implementation assumes every integer in this interval is supported. If the
service instead accepts discrete packages, leave the feature disabled and adapt
the capability policy before release. No Fragment wallet/API integration exists.

When enabled, the server chooses the method using the **net** Stars amount:
up to 50 -> existing live gift denominations (with a 50-Star ceiling); above 50 ->
the exact integer quantity via manual Fragment. An amount outside the confirmed
interval is rejected, not silently rounded down. Fragment requests require a
validated current Telegram username; users without one are directed to support.

Quotes persist their method for five minutes. Disabling the capability prevents
new Fragment reservations, including outstanding quotes, but does not erase or
strand already reserved requests. Replay of the same quote returns the original
request without another reserve/notification. Existing requests can be manually
completed/rejected with the current protected admin workflow. Fragment completion
requires a payout reference for the already performed send; the button does not
send Stars. No commission, automatic payout or automatic refund was added.

VIP priority and plan/expiry are snapshotted at request creation. Expiry or later
disabling VIP does not remove a historical request's priority. The admin list can
filter VIP/ordinary requests and sorts priority requests first. The normal/manual
approval, earned reserve and single settlement checks remain authoritative.

## Rollback

Disable Fragment first to stop new reservations. Restore the previous application
only after resolving or retaining a compatible handler for existing Fragment
requests. Additive migration 0058 has a non-destructive downgrade and must remain
applied; do not drop historical method/priority snapshots. No production financial
transaction or deployment is part of these tests.
