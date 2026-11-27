"""Real aggregate/limit queries; ordinary economics and account pause stay intact."""
# ruff: noqa: F811 -- imported pytest fixtures
import uuid
from datetime import timedelta

import pytest
from fastapi import HTTPException, Response
from sqlalchemy.schema import CreateTable

from app import about, listing_details, seller_vip
from app.models import Deal, Favorite, ListingLike, PublicationRules
from app.publication_quota import publication_rules, require_free_slot, require_vip_slot
from test_chat_lifecycle_db import db as db
from test_seller_vip import vip_db as vip_db, start


@pytest.mark.asyncio
async def test_about_counts_real_completed_not_cancelled_paid_or_unfinished(db):
    bridge, buyer, seller, listing = db
    now = seller_vip.now_utc()
    with bridge.session.begin():
        for status, completed, cancelled in [("completed", now, None), ("completed", None, None),
                                              ("completed", now, now), ("cancelled", None, now), ("paid", None, None)]:
            bridge.session.add(Deal(id=uuid.uuid4(), listing_id=listing.id, buyer_id=buyer.id,
                seller_id=seller.id, status=status, price_af_coins=100, frozen_amount=0,
                platform_commission=0, seller_payout=100, completed_at=completed, cancelled_at=cancelled))
    response = Response()
    result = await about.project_about(response, buyer, bridge)
    assert result["users"] == 2 and result["completed_deals"] == 1
    assert result["statistics_source"] == "database" and result["founded_year"] == 2026
    assert len(result["games"]) == 2 and result["founder"]["name"] == "Maxim"
    assert result["founder"]["photo_url"] is None
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.asyncio
async def test_vip_caps_are_total_active_and_expiry_preserves_listings(vip_db):
    bridge, _, seller, listing = vip_db
    with bridge.session.bind.begin() as conn:
        conn.execute(CreateTable(PublicationRules.__table__))
    sub, _ = await seller_vip.purchase(bridge, seller.id, start())
    with bridge.session.begin():
        sub.car_limit = 1
        current = await publication_rules(bridge, seller)
        assert current["free_limit"] == current["active_count"] == 1
        assert current["vip_limit_reached"] and not current["payment_required"]
        with pytest.raises(HTTPException) as error:
            await require_free_slot(bridge, seller)
        assert error.value.detail["code"] == "seller_vip_listing_limit"
        with pytest.raises(HTTPException):
            await require_vip_slot(bridge, seller)  # Also called on paid fulfillment.
        listing.status = "paused"
        await bridge.flush()
        assert (await publication_rules(bridge, seller))["active_count"] == 0
        assert await require_vip_slot(bridge, seller)
        listing.status = "active"
        sub.expires_at = seller_vip.now_utc() - timedelta(seconds=1)
        sub.starts_at = sub.expires_at - timedelta(days=30)
        await bridge.flush()
        current = await publication_rules(bridge, seller)
        assert not current["vip_active"] and current["free_limit"] == 5
        assert listing.status == "active" and listing.deleted_at is None


@pytest.mark.asyncio
async def test_seller_badge_uses_live_subscription_and_hides_after_expiry(vip_db):
    bridge, buyer, seller, listing = vip_db
    with bridge.session.bind.begin() as conn:
        for model in (Favorite, ListingLike):
            conn.execute(CreateTable(model.__table__))
    sub, _ = await seller_vip.purchase(bridge, seller.id, start())
    with bridge.session.begin():
        context = await listing_details.seller_context(listing.id, 12, 0, buyer, bridge)
        assert context.vip_active and context.vip_expires_at == sub.expires_at and context.server_now
        sub.starts_at -= timedelta(days=31)
        sub.expires_at = seller_vip.now_utc() - timedelta(seconds=1)
        await bridge.flush()
        context = await listing_details.seller_context(listing.id, 12, 0, buyer, bridge)
        assert not context.vip_active and context.vip_expires_at is None


def test_founder_avatar_only_explicit_https_setting(monkeypatch):
    from types import SimpleNamespace
    for value, expected in [("", None), ("javascript:alert(1)", None),
                            ("https://name:secret@example.org/a.jpg", None),
                            ("https://example.org/founder.jpg", "https://example.org/founder.jpg")]:
        monkeypatch.setattr(about, "get_settings", lambda: SimpleNamespace(about_founder_photo_url=value))
        assert about.founder_photo() == expected
