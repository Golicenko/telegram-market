"""Only disposable PostgreSQL schemas; never existing videos or production."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app import account_video_processing as processing, account_video_volume as volume
from app.config import Settings
from app.models import AccountVideo, Listing, User
from test_referral_bonus_postgres import isolated_pg, apply_revisions


def linked_account(owner, video_id):
    return Listing(
        id=uuid.uuid4(),
        seller_id=owner,
        listing_type="regular",
        product_kind="account",
        game_version="car_parking_1",
        status="active",
        brand="Cleanup regression fixture",
        model="",
        power_hp=None,
        max_speed_kph=None,
        description="Isolated fixture",
        price_af_coins=100,
        video_asset_id=video_id,
    )


@pytest.mark.asyncio
async def test_additive_video_migration_preserves_existing_ready_asset():
    async with isolated_pg(tables=False) as (engine, _):
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda sync: apply_revisions(sync, target="0055_account_autodelivery")
            )
            owner, video = uuid.uuid4(), uuid.uuid4()
            await connection.execute(
                text(
                    "INSERT INTO users(id,telegram_id,first_name,role) VALUES(:id,99001,'Isolated test','user')"
                ),
                {"id": owner},
            )
            await connection.execute(
                text(
                    "INSERT INTO account_videos(id,owner_id,object_key,content_type,size_bytes,ready) VALUES(:id,:owner,'account-videos/existing-object','video/mp4',100,true)"
                ),
                {"id": video, "owner": owner},
            )
            await connection.run_sync(
                lambda sync: apply_revisions(
                    sync,
                    target="0056_account_video_processing",
                    after="0055_account_autodelivery",
                )
            )
            row = (
                await connection.execute(
                    text(
                        "SELECT object_key,ready,processing_status,processing_meta,processed_key FROM account_videos WHERE id=:id"
                    ),
                    {"id": video},
                )
            ).one()
            assert tuple(row) == (
                "account-videos/existing-object",
                True,
                None,
                None,
                None,
            )
            assert (
                await connection.scalar(text("SELECT count(*) FROM account_videos"))
            ) == 1


@pytest.mark.asyncio
async def test_cleanup_keeps_legacy_and_all_listing_playback_references(
    tmp_path, monkeypatch
):
    settings = Settings(
        bot_token="",
        account_video_volume_dir=str(tmp_path),
        account_video_storage="volume",
    )
    monkeypatch.setattr(processing, "get_settings", lambda: settings)
    monkeypatch.setattr(volume, "get_settings", lambda: settings)
    async with isolated_pg() as (_, sessions):
        owner = uuid.uuid4()
        cases = []
        old = datetime.now(UTC) - timedelta(days=8)
        async with sessions() as session, session.begin():
            session.add(
                User(
                    id=owner, telegram_id=99002, first_name="Cleanup test", role="user"
                )
            )
            await session.flush()
            for index, listing_status in enumerate(
                (None, "active", "sold", "deleted", "legacy", "fresh", "processing")
            ):
                video_id = uuid.uuid4()
                key = f"volume:videos/{video_id.hex}/" + str(index + 1) * 64
                linked = listing_status in {"active", "sold", "deleted"}
                output = (
                    f"volume:videos/{video_id.hex}/" + str(index + 2) * 64
                    if linked
                    else None
                )
                status = (
                    None
                    if listing_status == "legacy"
                    else "processing"
                    if listing_status == "processing"
                    else "ready"
                    if linked
                    else "queued"
                )
                session.add(
                    AccountVideo(
                        id=video_id,
                        owner_id=owner,
                        object_key=key,
                        processed_key=output,
                        content_type="video/mp4",
                        size_bytes=12,
                        ready=linked or listing_status == "legacy",
                        processing_status=status,
                        created_at=datetime.now(UTC)
                        if listing_status == "fresh"
                        else old,
                    )
                )
                await session.flush()
                if linked:
                    session.add(
                        Listing(
                            id=uuid.uuid4(),
                            seller_id=owner,
                            listing_type="regular",
                            product_kind="account",
                            game_version="car_parking_1",
                            status="paused"
                            if listing_status == "deleted"
                            else listing_status,
                            brand="Cleanup fixture",
                            model="",
                            power_hp=None,
                            max_speed_kph=None,
                            description="Isolated fixture",
                            price_af_coins=100,
                            video_asset_id=video_id,
                            deleted_at=old if listing_status == "deleted" else None,
                        )
                    )
                for asset in (key, output):
                    if asset:
                        path = volume.object_path(asset)
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(b"isolated file")
                cases.append((video_id, listing_status, key, output))
        await processing.cleanup_once(sessions)
        async with sessions() as session:
            for video_id, listing_status, key, output in cases:
                row = await session.get(AccountVideo, video_id)
                if listing_status in {"active", "sold", "deleted"}:
                    assert row.ready and row.processing_status == "ready_pruned"
                    assert volume.object_path(output).is_file()
                    assert not volume.object_path(key).exists()
                elif listing_status is None:
                    assert not row.ready and row.processing_status == "expired"
                    assert not volume.object_path(key).exists()
                else:
                    assert volume.object_path(key).is_file()
                    if listing_status == "legacy":
                        assert row.ready and row.processing_status is None
                    if listing_status == "fresh":
                        assert row.processing_status == "queued"
                    if listing_status == "processing":
                        assert row.processing_status == "processing"


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["volume", "s3"])
async def test_cleanup_removes_cancelled_attempt_outputs_but_keeps_live_playback(
    tmp_path, monkeypatch, provider
):
    """Output copied before cancellation must remain durably collectible.

    S3 is a local object-store double: test the real DB cleanup and deletion
    commands without contacting any configured bucket or credentials.
    """
    from app import account_video

    settings = Settings(
        bot_token="",
        account_video_volume_dir=str(tmp_path),
        account_video_storage=provider,
    )
    monkeypatch.setattr(processing, "get_settings", lambda: settings)
    monkeypatch.setattr(volume, "get_settings", lambda: settings)
    objects = set()
    deleted = []

    class IsolatedS3:
        def delete_object(self, *, Bucket, Key):
            assert Bucket == "isolated-test-bucket"
            deleted.append(Key)
            objects.discard(Key)

    monkeypatch.setattr(
        account_video, "storage", lambda: (IsolatedS3(), "isolated-test-bucket")
    )

    def key(video_id, marker):
        if provider == "volume":
            return f"volume:videos/{video_id.hex}/" + marker * 64
        return f"account-videos/{video_id}/{marker * 32}"

    def put(asset):
        objects.add(asset)
        if provider == "volume":
            path = volume.object_path(asset)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"isolated attempted output")

    def exists(asset):
        return (
            volume.object_path(asset).is_file()
            if provider == "volume"
            else asset in objects
        )

    async with isolated_pg() as (_, sessions):
        owner, cancelled, linked = (uuid.uuid4() for _ in range(3))
        old = datetime.now(UTC) - timedelta(days=8)
        cancelled_source = key(cancelled, "a")
        cancelled_outputs = [key(cancelled, "b"), key(cancelled, "c")]
        linked_source = key(linked, "a")
        previous_output, playback = key(linked, "b"), key(linked, "c")
        cancelled_upload = (
            f"account-uploads/{owner}/{uuid.uuid4()}" if provider == "s3" else None
        )
        linked_upload = (
            f"account-uploads/{owner}/{uuid.uuid4()}" if provider == "s3" else None
        )
        removed = [
            cancelled_source,
            *cancelled_outputs,
            linked_source,
            previous_output,
            *filter(None, [cancelled_upload, linked_upload]),
        ]
        for asset in [*removed, playback]:
            put(asset)
        async with sessions() as session, session.begin():
            session.add(
                User(
                    id=owner, telegram_id=99003, first_name="Attempt test", role="user"
                )
            )
            await session.flush()
            session.add_all(
                [
                    AccountVideo(
                        id=cancelled,
                        owner_id=owner,
                        object_key=cancelled_source,
                        content_type="video/mp4",
                        size_bytes=12,
                        ready=False,
                        processing_status="cancelled",
                        processing_meta={
                            "output_keys": cancelled_outputs,
                            "upload_key": cancelled_upload,
                        },
                        created_at=old,
                    ),
                    AccountVideo(
                        id=linked,
                        owner_id=owner,
                        object_key=linked_source,
                        processed_key=playback,
                        content_type="video/mp4",
                        size_bytes=12,
                        ready=True,
                        processing_status="ready",
                        processing_meta={
                            # A previous worker may have written a stale output;
                            # the active processed key must never be deleted.
                            "output_keys": [previous_output, playback],
                            "upload_key": linked_upload,
                        },
                        created_at=old,
                    ),
                ]
            )
            await session.flush()
            session.add(linked_account(owner, linked))
        await processing.cleanup_once(sessions)
        assert all(not exists(asset) for asset in removed)
        assert exists(playback)
        if provider == "s3":
            assert set(deleted) == set(removed)
            assert playback not in deleted
        async with sessions() as session:
            abandoned = await session.get(AccountVideo, cancelled)
            active = await session.get(AccountVideo, linked)
            assert not abandoned.ready and abandoned.processing_status == "expired"
            assert active.ready and active.processing_status == "ready_pruned"
            assert active.processed_key == playback


@pytest.mark.asyncio
@pytest.mark.parametrize("linked", [False, True])
async def test_cleanup_resumes_durable_delete_after_worker_restart(
    tmp_path, monkeypatch, linked
):
    settings = Settings(
        bot_token="",
        account_video_volume_dir=str(tmp_path),
        account_video_storage="volume",
    )
    monkeypatch.setattr(processing, "get_settings", lambda: settings)
    monkeypatch.setattr(volume, "get_settings", lambda: settings)
    async with isolated_pg() as (_, sessions):
        owner, video_id = uuid.uuid4(), uuid.uuid4()
        source = f"volume:videos/{video_id.hex}/" + "a" * 64
        stale_output = f"volume:videos/{video_id.hex}/" + "b" * 64
        playback = f"volume:videos/{video_id.hex}/" + "c" * 64
        # Simulate a crash after the first key was deleted, before final DB
        # acknowledgement. Repeating deletion of a missing key must be safe.
        for asset in (stale_output, playback):
            path = volume.object_path(asset)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"isolated restart fixture")
        async with sessions() as session, session.begin():
            session.add(
                User(
                    id=owner, telegram_id=99004, first_name="Restart test", role="user"
                )
            )
            await session.flush()
            session.add(
                AccountVideo(
                    id=video_id,
                    owner_id=owner,
                    object_key=source,
                    processed_key=playback if linked else None,
                    content_type="video/mp4",
                    size_bytes=12,
                    ready=linked,
                    processing_status="pruning" if linked else "expiring",
                    processing_meta={
                        "output_keys": [stale_output, playback],
                        "cleanup_keys": [source, stale_output]
                        if linked
                        else [source, stale_output, playback],
                        "cleanup_linked": linked,
                    },
                    created_at=datetime.now(UTC) - timedelta(days=8),
                )
            )
            await session.flush()
            if linked:
                session.add(linked_account(owner, video_id))
        await processing.cleanup_once(sessions)
        assert not volume.object_path(source).exists()
        assert not volume.object_path(stale_output).exists()
        assert volume.object_path(playback).is_file() == linked
        async with sessions() as session:
            row = await session.get(AccountVideo, video_id)
            assert row.ready == linked
            assert row.processing_status == ("ready_pruned" if linked else "expired")
        # Completed cleanup stays idempotent after yet another restart.
        await processing.cleanup_once(sessions)
        assert volume.object_path(playback).is_file() == linked


@pytest.mark.asyncio
async def test_worker_reclaims_stale_processing_claim_but_not_live_claim(
    tmp_path, monkeypatch
):
    from test_account_video_processing import binaries, generate

    async with isolated_pg() as (_, sessions):
        ffmpeg, ffprobe = binaries()
        settings = Settings(
            bot_token="",
            account_video_volume_dir=str(tmp_path),
            account_video_storage="volume",
            ffmpeg_binary=ffmpeg,
            ffprobe_binary=ffprobe,
        )
        monkeypatch.setattr(processing, "get_settings", lambda: settings)
        monkeypatch.setattr(volume, "get_settings", lambda: settings)
        owner, stale_id, live_id = (uuid.uuid4() for _ in range(3))
        now = datetime.now(UTC)
        tiny = generate(tmp_path / "tiny.mp4", seconds=1, width=320, height=180)
        old_claim, live_claim = uuid.uuid4().hex, uuid.uuid4().hex
        async with sessions() as session, session.begin():
            session.add(
                User(id=owner, telegram_id=99005, first_name="Claim test", role="user")
            )
            await session.flush()
            for video_id, stamp, claim in (
                (stale_id, now - timedelta(minutes=21), old_claim),
                (live_id, now, live_claim),
            ):
                key = f"volume:videos/{video_id.hex}/" + "a" * 64
                source = volume.object_path(key)
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(tiny.read_bytes())
                session.add(
                    AccountVideo(
                        id=video_id,
                        owner_id=owner,
                        object_key=key,
                        content_type="video/mp4",
                        size_bytes=source.stat().st_size,
                        ready=False,
                        processing_status="processing",
                        processing_meta={
                            "started_at": stamp.isoformat(),
                            "claim": claim,
                            "attempts": 1,
                            "progress": 20,
                        },
                        created_at=now - timedelta(minutes=22),
                    )
                )
        assert await processing.process_one(sessions) is True
        async with sessions() as session:
            recovered = await session.get(AccountVideo, stale_id)
            live = await session.get(AccountVideo, live_id)
            assert recovered.ready and recovered.processing_status == "ready"
            assert recovered.processing_meta["claim"] != old_claim
            assert recovered.processing_meta["attempts"] == 2
            assert recovered.processing_meta["progress"] == 100
            assert recovered.processed_key in recovered.processing_meta["output_keys"]
            assert volume.object_path(recovered.processed_key).is_file()
            assert live.processing_status == "processing" and not live.ready
            assert live.processing_meta["claim"] == live_claim
            assert live.processing_meta["attempts"] == 1
            assert live.processed_key is None
        # A non-stale in-flight worker remains the sole owner of its claim.
        assert await processing.process_one(sessions) is False


@pytest.mark.asyncio
async def test_cancel_after_real_optimize_cannot_publish_or_orphan_output(
    tmp_path, monkeypatch
):
    from app.account_video import cancel_video
    from test_account_video_processing import binaries, generate

    async with isolated_pg() as (_, sessions):
        ffmpeg, ffprobe = binaries()
        settings = Settings(
            bot_token="",
            account_video_volume_dir=str(tmp_path),
            account_video_storage="volume",
            ffmpeg_binary=ffmpeg,
            ffprobe_binary=ffprobe,
        )
        monkeypatch.setattr(processing, "get_settings", lambda: settings)
        monkeypatch.setattr(volume, "get_settings", lambda: settings)
        owner, video_id = uuid.uuid4(), uuid.uuid4()
        key = f"volume:videos/{video_id.hex}/" + "a" * 64
        source = volume.object_path(key)
        source.parent.mkdir(parents=True, exist_ok=True)
        tiny = generate(tmp_path / "tiny.mp4", seconds=1, width=320, height=180)
        source.write_bytes(tiny.read_bytes())
        async with sessions() as session, session.begin():
            user = User(
                id=owner, telegram_id=99006, first_name="Cancel race test", role="user"
            )
            session.add(user)
            await session.flush()
            session.add(
                AccountVideo(
                    id=video_id,
                    owner_id=owner,
                    object_key=key,
                    content_type="video/mp4",
                    size_bytes=source.stat().st_size,
                    ready=False,
                    processing_status="queued",
                )
            )
        original_optimize = processing.optimize
        cancelled = []

        async def optimize_then_cancel(*args, **kwargs):
            # Deterministic race window, using the real FFmpeg implementation
            # and the real cancellation command rather than a fake encoder.
            result = await original_optimize(*args, **kwargs)
            async with sessions() as session:
                response = await cancel_video(video_id, user=user, session=session)
                assert response["status"] == "cancelled"
            cancelled.append(video_id)
            return result

        monkeypatch.setattr(processing, "optimize", optimize_then_cancel)
        assert await processing.process_one(sessions) is True
        assert cancelled == [video_id]
        async with sessions() as session:
            row = await session.get(AccountVideo, video_id)
            assert row.processing_status == "cancelled" and not row.ready
            assert row.processed_key is None
            assert not row.processing_meta.get("output_keys")
        # The guard runs before copying/persisting output, so the private
        # storage contains the source only, with no orphan MP4 or .part file.
        files = [path for path in volume.volume_root().rglob("*") if path.is_file()]
        assert files == [source]
        assert await processing.process_one(sessions) is False
