# Compact deals, withdrawal balances and private photos — 2026-11-07

## Scope

- Four existing seller stages are compact. Three green marks mean seller actions finished, not buyer confirmation or settlement. Existing confirmation dialogs, deadlines, reminders and escrow are unchanged.
- Only withdrawal shows total available AF and earned/withdrawable AF separately. Other screens keep one total. A fresh authenticated /me read runs on opening withdrawal; a failed read shows retry, not a supposedly current cached amount.
- The existing gift quote remains authoritative, including its 30% fee and remainder. Insufficient earned AF (402, insufficient_withdrawable_af) and an amount below the smallest gift including fee (400, below_minimum_gift) are different errors.
- Photos use the existing chat command, nonce, transaction, outbox and notification. Text remains compatible. No financial commands are added.

## Private images

- POST /api/conversations/{conversation_id}/photos accepts multipart file, client_message_id, optional deal_id and body. It validates signed Telegram initData, participant, exact deal and active thread. A replay returns the original message; conversation locking prevents duplicate media/message/notification.
- JPEG/PNG/WebP/HEIC/HEIF are actually decoded through the existing Pillow/pillow-heif pipeline, orientation corrected, EXIF removed and converted to bounded JPEG (max 2560px, existing 64MP decoder limit, max 2MiB normalized content). Source limit 12MiB, batch UI limit four, atomic server limit ten photos/minute/sender/conversation. Existing upload concurrency, multipart byte/time limits and spool cleanup also apply.
- GET /api/conversations/{conversation_id}/photos/{image_id}?preview=true|false checks participant or server admin before selecting bytes. No public /uploads or /media URL is created. Cache-Control: private, no-store. Signed headers are attached by the existing API client; the page uses temporary blob URLs, revoked on leaving the chat/viewer.
- 480px previews are lazy loaded; full JPEG is fetched only when opening the viewer. Zoom/pan is limited to the viewer. Telegram Back closes the viewer first. Archived photos remain readable to their participants, but closed deals cannot receive new messages.
- A first-ever ordinary dialog without a conversation ID must be started with text before attaching a photo. Paid deals already have an ID. This does not create empty text messages merely to enable upload.

## Performance findings

An empty incremental result used to trigger a second fetch of the latest 100 messages. Every poll also repeated presence/read/unread-summary. The full-history fallback is removed; scoped read IDs accompany the existing incremental response. Unchanged bubbles keep DOM identity; older pages prepend without replacing photo nodes. A scope/epoch guard rejects stale chat/deal responses and coalesces overlapping polls. Read acknowledgements repeat only for a new final message; presence is at most once per 15 seconds. A steady idle cycle is two requests rather than six, plus that heartbeat. This is request-count analysis, not a claimed production latency measurement.

## Migration and release

- Additive revision 0054_private_chat_photos (after 0053_feedback_collection) creates private_chat_images and nullable media metadata on existing messages, then expands the message type constraint. No wallet columns or historical messages are rewritten.
- Existing PostgreSQL stores normalized data and thumbnail in private BYTEA columns. Include these in backup/capacity planning; this increases database storage. No new environment variable or external storage service is required.
- Back up and rehearse the migration in staging, then deploy through the existing controlled process. This change does not deploy automatically.
- Roll back application code without removing the additive schema or media. Downgrade refuses to delete stored private photos. An empty installation can downgrade normally. Do not delete user media to force a rollback.

## Verification

- Local full backend suite: 555 passed; 180 PostgreSQL/opt-in cases skipped without a dedicated local PostgreSQL.
- Browser state checks: 320x640, 390x844, 430x844; four stages, deadline controls, ID copy, three green marks, mobile overflow and withdrawal quote races.
- New dedicated PostgreSQL tests cover signed participant access, unauthorized reads, three decoded formats, malformed/large/unsupported files, concurrent UUID replay, atomic rate limit, receipt headers, old-text/wallet migration preservation, sale settlement exactly once and separate withdrawal errors.
- A separate live-browser job connects the actual Mini App to an isolated PostgreSQL-backed API with two signed test users. It exercises accept/ID, cancelled previews, three photos, lost-response retry, original/preview authorization, zoom/Back, unchanged DOM and seller transfer with funds still held. No real Telegram bot or payment is contacted.
- Physical iPhone/Android Telegram WebViews and real production traffic are not verified by a desktop browser. No production migration, payment, withdrawal or bulk message was executed.
