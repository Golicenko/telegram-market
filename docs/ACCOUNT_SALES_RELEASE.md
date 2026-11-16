# Account sales: opt-in release gate

## Scope

New `Listing.product_kind=account` uses the existing AF wallet, escrow,
Conversation, dispute and settlement commands. Legacy `account_listings` is
unchanged and never treated as a secure-delivery source. Car commissions and VIP
tariffs are unchanged. Bonus provenance is preserved by the existing settlement.

Accounts have three active free slots; each additional active publication costs
15 AF after explicit consent. Seller row locking, the existing unique
seller/request key and one DB transaction cover quota, debit and publication.
Editing is free; an account already exposed to a buyer cannot be republished.
Account VIP is a separate 5 XTR invoice for 24 hours, with no AF/referral credit.

Purchase creates a unique deal and encrypted grant under the existing Listing
lock. It enters `transfer_in_progress` immediately; this is NOT settlement.
Only the buyer's explicit protected request decrypts the grant. A checked
confirmation (after opening the grant and the existing 60s cooldown) runs the
shared settlement command once. Disputes freeze the hold and use existing
administrator decisions. No automatic payout or complaint-only refund was added.

## Required owner actions before enabling

1. Obtain confirmation that account transfers are permitted by CP1/CP2's
   developer. Both published EULAs grant non-transferable licences; this alone
   does not establish permission to sell accounts. Do not advertise official
   approval or guaranteed recovery protection.
   Sources: https://olzhass.net/Car_Parking_Multiplayer_EULA.html and
   https://olzhass.net/Car_Parking_Multiplayer-2_EULA.html .
2. Back up the database, rehearse migration 0055 in a disposable copy and check
   the existing car catalogue and balances. Never test with real payments.
3. Use the existing application Railway Volume (production mount verified as
   `/app/backend/uploads`, capacity 5 GB). With `ACCOUNT_VIDEO_STORAGE=auto`,
   `RAILWAY_VOLUME_MOUNT_PATH` is detected automatically when S3 is not set.
   Videos live in its private `.account-videos` directory; the legacy public
   `/uploads` mount explicitly rejects this directory. No new bucket, paid
   resource, database video blob or migration is required. For a different
   persistent mount use `ACCOUNT_VIDEO_VOLUME_DIR`; do not point at ephemeral
   container storage. Playback uses a one-hour encrypted capability, scoped to
   the authenticated viewer and immutable asset; it works without cookies in
   Telegram Web embeds. Native Range streaming rechecks the viewer/asset ACL.
   No Telegram initData, bot token or account credentials appear in media URLs.
   The capability itself is access-sensitive: application access logs redact
   the stream query, responses are no-store/no-referrer. Do not retain signed
   query strings in proxy logs. A viewer can share/download media while access
   is valid; this is not DRM or a guarantee against screen recording.
   Uploads are bounded to 100 MB by default, two concurrent streams per process,
   with size/container validation, timeout, free-space reserve and immutable
   content-hash final files. A repeated identical PUT is safe; replacing a ready
   video is rejected. Monitor volume capacity, back it up, and keep one app
   replica unless migrating to shared object storage. Controlled failed uploads
   remove their temporary files; a hard process kill can leave `.part` files or
   an unreferenced final file requiring owner-reviewed housekeeping. Do not
   delete referenced media to free space.

   Alternatively retain PRIVATE S3-compatible storage. Configure `ACCOUNT_S3_ENDPOINT`
   (HTTPS), `ACCOUNT_S3_REGION`, `ACCOUNT_S3_BUCKET`, `ACCOUNT_S3_ACCESS_KEY`,
   `ACCOUNT_S3_SECRET_KEY` via the deployment secret manager. Least privileges:
   Get/Head/Put/Copy on the two account prefixes only. No public listing/access.
   CORS: exact staging/production origins, PUT/GET/HEAD and Content-Type;
   allow the client's signed request headers. Test actual browser PUT from both
   iOS and Android. Server validates size/type signature and copies a final
   immutable object to a new random key; original upload URLs cannot overwrite
   a published review. Configure lifecycle deletion for temporary
   `account-uploads/` objects after a day, NOT `account-videos/`.
4. Generate a random 32-byte AES key securely OUTSIDE Git/chat/logs. Store JSON
   key-ID/base64 pairs in `ACCOUNT_SECRET_KEYS`, select the active ID using
   `ACCOUNT_SECRET_ACTIVE_KEY`. No key is supplied in this repository.
   `ACCOUNT_SECRET_RETENTION_DAYS=1` applies after final completion/cancellation;
   unresolved disputes retain encrypted credentials. Existing grants remain
   readable with their keys even when new sales are disabled.
5. Run isolated backend/PG/browser CI, real staging video upload/playback and
   test-bot invoice checks. Browser emulation is not a physical-device test.
   Check MP4 playback on iPhone (H.264 recommended) and WebM on Android; header
   verification is not transcoding or a guarantee of codec compatibility.
6. Only after approval set `ACCOUNT_SALES_ENABLED=true`. No automatic deployment
   or production financial test is part of this change.

## Key rotation and retention

Keep old AND new keys in the manager, select the new active ID, then run
`python -m app.account_key_rotation` for a count-only dry run.
`python -m app.account_key_rotation --apply` re-encrypts 100-row transactional
batches with context authentication. Keep all old keys until zero live rows use
them and the backup-retention policy allows their retirement. If a batch fails,
earlier batches are valid and the command can be resumed; never delete keys to
"fix" an error. Plaintext is not printed.

The existing process lifecycle starts a bounded 60s cleanup loop. It erases
completed/cancelled grants and corresponding source credentials past the agreed
one-day retention, never unresolved disputes. Deleting an unpurchased listing
erases its source credentials immediately. Retention is logical removal from the
active database; encrypted backups require their own retention/key policy.

## Private support photos

New support uploads use `/api/uploads?purpose=support` and cannot be fetched via
public `/api/media`. Ticket-author/participants/staff ACLs protect preview/full
photo endpoints. The existing photo viewer provides zoom and Back/close. Old
support-only database images are made private by migration 0055; images also
used in public listings/training remain public in those explicit uses. Legacy
external URLs are not fetched server-side, and missing local files cannot be
reconstructed. Already cached public images cannot be made unseen retroactively.

## Routes / schema

- GET `/api/account-publication-rules`
- POST/PATCH `/api/account-products[/{listing_id}]`
- POST `/api/account-videos`, PUT `/{id}/content` (volume),
  POST `/{id}/complete`, GET `/{id}/play`, GET/HEAD `/{id}/stream` (volume).
  Existing S3 assets retain their provider without a data migration.
- POST `/api/account-products/{id}/pin`, GET `/api/account-pins/{id}`
- POST `/api/account-deals/{id}/credentials` (buyer only, no-store)
- POST `/api/account-deals/{id}/confirm` (`checked_access=true`)
- GET `/api/support/tickets/{id}/photo` and `/api/support/images/{id}`
- Existing listings API accepts optional product_kind/game_version filters.
- Admin financial summary counts completed account sales from DB, not clicks.
- Migration 0055 adds videos/secrets/grants/pin receipts, subtype fields and
  private support media; it does not convert or delete legacy listings.

## Rollback

Disable NEW account sales with the feature flag in this account-aware release;
preserve keys, video volume/bucket and the additive schema. Do not roll back to
an S3-only binary after accepting volume videos: it cannot play those assets.
Continue existing obligations,
grant access, disputes and pending payment reconciliation. An old car-only binary
cannot serialize account rows with NULL car stats, so do not roll back to it once
accounts exist. Never drop grant/key data to roll back. The migration downgrade
refuses if new account data or private support images exist. Production monetary
state was not changed by implementation/tests.
