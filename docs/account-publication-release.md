# Account publication / media update

## Scope

- Account create/edit uses the existing full-page form view and Back navigation.
  An unfinished form survives navigation only in memory; page close clears it.
  Passwords never enter localStorage, analytics or public listing responses.
- Backend publication rules supply the active/free count, additional-publication
  price and VIP terms. Three free slots / 15 AF and 5 Stars / 24 hours are unchanged.
- VIP is checked by default for new accounts. Publication commits first; only
  then the existing account-pin invoice opens. Unchecked means no pin request.
  Cancelled checkout leaves the ordinary published listing; payment verification
  and activation remain server-authoritative and idempotent.
- Account details reuse one media area: cover first, video second. Changing the
  slide does not fetch the video. Play requests protected playback. Minor listing
  refreshes preserve the existing player/time; leaving pauses it.
- Confirmed purchase reuses the existing check animation for 800 ms, without
  delaying the exact deal-chat navigation. One display per deal per app session.

## Why upload was slow / what changes

Previously the entire raw upload started only on Publish; no 480p preparation
existed. Upload now starts on selection while the seller fills the form. XHR
reports actual transferred bytes; processing progress is separate. The in-memory
upload id is reused after a failed response, avoiding retransmission of an already
accepted source. Cancel and bounded processing retry are authenticated commands.

Browser transcoding is deliberately not installed: WebCodecs / codec availability
varies in Telegram WebViews; a bundled WASM encoder would consume substantial
memory/CPU. The existing server/volume handles one FFmpeg job at a time, outside
HTTP requests. Input is streamed to disk; no video blobs are stored in PostgreSQL.

Output is MP4 H.264/yuv420p + AAC, preserving proportions, up to 854×480 landscape
or 480×854 portrait, normally capped at 1.4 Mbps video / 96 kbps audio. Small
compatible H.264/AAC inputs are remuxed, not re-encoded or upscaled. Faststart
puts MP4 metadata first. Existing protected access, signed playback and HTTP
Range are preserved. Legacy ready videos retain their original keys and format.

Initial source upload is still bounded by the existing 100 MiB default. Server
compression **does not shorten that initial network transfer**; it saves storage
and playback bandwidth. Early upload overlaps form entry. See actual synthetic
measurements and their limitations in [the benchmark](account-video-processing-benchmark.md).

## Queue, storage and resource limits

- Migration `0056_account_video_processing`: three nullable columns and one index
  on existing `account_videos`; no rewrite/backfill of historical media.
- FIFO database queue, row locking / skip-locked claim and a unique claim fence.
  One serial worker per existing app process; FFmpeg uses one codec/filter thread.
  The production start command currently runs one Uvicorn process. Do not add
  replicas/workers without reviewing the desired global encoding concurrency.
- Encoding is bounded to 10 minutes, each S3 transfer to 2 minutes, probe to
  20 seconds. A crashed claim is recoverable after 20 minutes, at most 3 attempts.
  The UI can time out its check after 10 minutes without deleting the source;
  rechecking reuses the same upload id.
- Per owner: at most 3 recently pending uploads and configurable 20 starts/day;
  no charge for starting video processing. Existing raw-upload 2-slot / 300 s
  limits and free-disk reserve remain in place.
- Claim-owned output keys are recorded before file copy/upload. Cancelled or
  failed finalization cannot create untracked files. Cleanup runs hourly and
  persists its own pending keys so restart retries are safe.
- Only new pipeline uploads older than 7 days are eligible. All listing references
  (active, sold, deleted) protect playback. Only temporary originals / obsolete
  attempts are pruned for linked listings; unlinked abandoned files expire.
  Legacy NULL-status media is untouched. Stale `.part` files are confined to the
  private video directory. No existing listing/video is deleted during release.
- Read-only Railway snapshot before release: app limit 8 vCPU / 8 GB, observed
  memory about 0.41 GB and CPU about 0.006 core at inspection. Existing volume
  is 5 GB; no paid storage/database is provisioned. This is not an encoding load
  test or a guarantee of future headroom. Runtime disk checks remain authoritative.

## Config and release

New settings (defaults work with the Docker image and existing volume):

| Variable | Default | Purpose |
| --- | --- | --- |
| `ACCOUNT_VIDEO_PROCESSING_ENABLED` | `true` | Queue newly uploaded media for preparation |
| `ACCOUNT_VIDEO_DAILY_LIMIT` | `20` | Starts per owner in rolling 24 hours |
| `ACCOUNT_VIDEO_MAX_DURATION_SECONDS` | `240` | Accepted source duration |
| `FFMPEG_BINARY` / `FFPROBE_BINARY` | `ffmpeg` / `ffprobe` | Installed by Dockerfile |

No new secrets. Existing encryption keys, volume path and S3 configuration remain
unchanged. The additive migration must run before the new binary (existing
Railway migration runner, separate from `start.sh`). Take the normal DB/volume backup before an approved
release; verify staging upload, playback, publication and existing car flow.

**No automatic Deploy, merge, mass messages or real payments are performed for
this change.** PR checks use temporary DB schemas, generated media and fake invoice
transport; they do not prove a real Stars checkout on production.

Rollback: stop rollout / restore the prior frontend only, or ship an account-aware
hotfix retaining `processed_key` playback support. Do not blindly restore a binary
that only serves raw originals after pruning. Keep the additive schema and media.
Migration downgrade refuses while processed videos exist; migrate/copy playback
objects and verify access before any destructive downgrade. Disabling new-input
processing is not deletion of existing jobs or processed videos.

## Verification evidence / limits

Local full backend: 590 passed / 202 skipped (no PostgreSQL configured locally;
dedicated browser/benchmark steps opt in). Node: 232 passed. Full-page form
browser checks pass at 320/390/430 CSS px; real media browser tests also cover
lazy playback, seek, speeds, refresh, photo switch and stale swipe cleanup.
The dedicated CI additionally executes real isolated PostgreSQL migration,
cleanup, seller form → upload → FFmpeg → publication → buyer purchase/chat
and existing settlement/authorization tests.

No physical iPhone/Android or real iPhone MOV recording was available. Generated
MOV/portrait tests and Chromium mobile emulation are not physical-device tests.
Manual Telegram WebView and real staging Stars verification remain release
checks for the owner, without charging production users.
