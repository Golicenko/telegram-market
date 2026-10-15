"""Real signed HTTP, image decoders and PostgreSQL. No production/Telegram calls."""
import asyncio
from io import BytesIO
import uuid

import httpx
from PIL import Image
import pytest
from sqlalchemy import func, select

from app import publications, services
from app.models import Listing, ListingImage, PublicationDraft, StarPayment, UploadedImage, WalletTransaction
from app.upload_guard import ImageUploadGuard
from test_catalog_and_acceptance_postgres import headers
from test_publication_stars_postgres import app, listing_payload, payment
from test_referral_bonus_postgres import isolated_pg, signed_login


async def upload(client, user, number, fmt="PNG"):
    with Image.new("RGB", (80, 60), (number * 20, 30, 100)) as image:
        content = BytesIO()
        image.save(content, fmt)
    response = await client.post("/api/uploads", headers=headers(user), files={"file": ("wrong.bin", content.getvalue(), "application/octet-stream")})
    assert response.status_code == 201, response.text
    return response.json()["url"]


@pytest.mark.asyncio
@pytest.mark.parametrize("game,photo_count", [("car_parking_1", 1), ("car_parking_1", 5), ("car_parking_2", 10)])
async def test_upload_publish_profile_edit_and_reopen(game, photo_count):
    async with isolated_pg() as (engine, sessions):
        seller = await signed_login(sessions, 99701)
        buyer = await signed_login(sessions, 99702)
        application = app(sessions)
        application.add_middleware(ImageUploadGuard)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://test") as client:
            formats = ["JPEG", "PNG", "WEBP", "HEIF", "AVIF", "GIF", "BMP", "TIFF", "JPEG", "PNG"]
            urls = [await upload(client, seller, n, formats[n]) for n in range(photo_count)]
            payload = {**listing_payload().model_dump(mode="json"), "game_version": game, "image_urls": urls}
            responses = await asyncio.gather(*[client.post("/api/listings", headers=headers(seller), json=payload) for _ in range(2)])
            assert all(r.status_code == 201 for r in responses), [r.text for r in responses]
            listing_id = responses[0].json()["id"]
            assert responses[1].json()["id"] == listing_id
            endpoint = f"/api/listings/{listing_id}"
            listing = (await client.get(endpoint, headers=headers(buyer))).json()
            assert listing["images"] == urls and listing["game_version"] == game
            assert listing_id in {r["id"] for r in (await client.get("/api/listings?type=regular", headers=headers(buyer))).json()}
            assert listing_id in (await client.get("/api/profile", headers=headers(seller))).text
            assert (await client.patch(endpoint, headers=headers(buyer), json={"description": "Not mine"})).status_code == 403
            # No replacement photos => keep all original photos and never charge.
            edited = await client.patch(endpoint, headers=headers(seller), json={"description": " New description ", "price_af_coins": "123.45"})
            assert edited.status_code == 200, edited.text
            assert edited.json()["images"] == urls and edited.json()["description"] == "New description"
            replacement = await upload(client, seller, 11, "PNG")
            edited = await client.patch(endpoint, headers=headers(seller), json={"image_urls": [replacement]})
            assert edited.status_code == 200 and edited.json()["images"] == [replacement]
        # Dispose/reopen database connections and ASGI app: media is not a temp
        # filesystem path and survives this application/pool restart boundary.
        await engine.dispose()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app(sessions)), base_url="http://test") as client:
            assert (await client.get(endpoint, headers=headers(buyer))).json()["images"] == [replacement]
            for url in urls + [replacement]:
                response = await client.get(url)
                assert response.status_code == 200
                with Image.open(BytesIO(response.content)) as image:
                    image.load()
                    assert image.format == "JPEG"
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(Listing)) == 1
            assert await session.scalar(select(func.count()).select_from(ListingImage)) == 1
            assert await session.scalar(select(func.count()).select_from(WalletTransaction)) == 0
            assert await session.scalar(select(func.count()).select_from(StarPayment)) == 0


@pytest.mark.asyncio
async def test_concurrent_upload_retry_and_invalid_references_do_not_publish_or_charge():
    async with isolated_pg() as (_, sessions):
        seller = await signed_login(sessions, 99711)
        other = await signed_login(sessions, 99712)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app(sessions)), base_url="http://test") as client:
            urls = await asyncio.gather(*[upload(client, seller, 1) for _ in range(4)])
            assert len(set(urls)) == 1
            foreign = await upload(client, other, 1)
            assert foreign != urls[0]
            for invalid in [foreign, "/api/media/invalid", f"/api/media/{uuid.uuid4()}", "javascript:alert(1)"]:
                payload = {**listing_payload().model_dump(mode="json"), "image_urls": [invalid]}
                result = await client.post("/api/listings", headers=headers(seller), json=payload)
                assert result.status_code == 422, result.text
            corrupt = await client.post("/api/uploads", headers=headers(seller), files={"file": ("fake.jpg", b"<svg>bad</svg>", "image/jpeg")})
            assert corrupt.status_code == 415
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(UploadedImage)) == 2
            assert await session.scalar(select(func.count()).select_from(Listing)) == 0
            assert await session.scalar(select(func.count()).select_from(WalletTransaction)) == 0


@pytest.mark.asyncio
async def test_sixth_paid_photo_publication_survives_commit_failure_and_retry(monkeypatch):
    async with isolated_pg() as (engine, sessions):
        seller = await signed_login(sessions, 99721)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app(sessions)), base_url="http://test") as client:
            photo = await upload(client, seller, 1, "HEIF")
            for n in range(5):
                payload = {**listing_payload(n).model_dump(mode="json"), "image_urls": [photo]}
                assert (await client.post("/api/listings", headers=headers(seller), json=payload)).status_code == 201
            payload = {**listing_payload(6).model_dump(mode="json"), "image_urls": [photo]}
            assert (await client.post("/api/listings", headers=headers(seller), json=payload)).status_code == 402
            draft = (await client.post("/api/publication-drafts", headers=headers(seller), json=payload)).json()
            assert draft["price_stars"] == 5 and draft["status"] == "draft"
            endpoint = "/api/publication-drafts/" + draft["id"]
            # Invoice cancel/close never credits, publishes or destroys saved photos.
            assert (await client.get(endpoint, headers=headers(seller))).json()["listing_id"] is None
            original_create = services.create_listing
            async def fail_once(*args, **kwargs):
                raise RuntimeError("simulated database unavailable after confirmed receipt")
            monkeypatch.setattr(services, "create_listing", fail_once)
            receipt = payment(draft, "isolated-confirmed-photo-publication")
            async with sessions() as session:
                await publications.receive_payment(session, seller.telegram_id, receipt)
                await publications.fulfill(session, uuid.UUID(draft["id"]))
            pending = (await client.get(endpoint, headers=headers(seller))).json()
            assert pending["status"] == "paid" and pending["listing_id"] is None
            monkeypatch.setattr(services, "create_listing", original_create)
        await engine.dispose()
        async def retry():
            async with sessions() as session:
                await publications.receive_payment(session, seller.telegram_id, receipt)
                await publications.fulfill(session, uuid.UUID(draft["id"]))
        await asyncio.gather(retry(), retry())
        async with sessions() as session:
            saved = await session.get(PublicationDraft, uuid.UUID(draft["id"]))
            assert saved.status == "published" and saved.listing_id
            assert await session.scalar(select(func.count()).select_from(Listing)) == 6
            assert await session.scalar(select(func.count()).select_from(StarPayment)) == 1
            assert await session.scalar(select(func.count()).select_from(WalletTransaction)) == 0
            assert await session.scalar(select(ListingImage.url).where(ListingImage.listing_id == saved.listing_id)) == photo
