import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.models import Listing, ListingLike, ListingView, User
from app.routes import like_listing, record_listing_view, unlike_listing


def make_user() -> User:
    return User(id=uuid.uuid4(), telegram_id=101, first_name="Viewer", role="user")


def make_listing(seller_id: uuid.UUID, views: int = 0) -> Listing:
    return Listing(
        id=uuid.uuid4(), seller_id=seller_id, listing_type="regular", status="active",
        brand="Car", model="", power_hp=1, max_speed_kph=1, description="Car",
        price_af_coins=1, views_count=views, pinned=False,
    )


class FakeSession:
    def __init__(self, *, listing, scalars=None):
        self.listing = listing
        self.scalars = list(scalars or [])
        self.commits = 0
        self.executed = []

    async def scalar(self, _statement):
        return self.scalars.pop(0) if self.scalars else None

    async def get(self, model, _identifier):
        return self.listing if model is Listing else None

    async def execute(self, statement):
        self.executed.append(statement)

    async def commit(self):
        self.commits += 1

    async def refresh(self, _value):
        return None


def test_engagement_tables_prevent_duplicate_user_reactions():
    view_unique = next(item for item in ListingView.__table__.constraints if item.name == "uq_listing_view_listing_user")
    like_unique = next(item for item in ListingLike.__table__.constraints if item.name == "uq_listing_like_listing_user")
    assert [column.name for column in view_unique.columns] == ["listing_id", "user_id"]
    assert [column.name for column in like_unique.columns] == ["listing_id", "user_id"]


@pytest.mark.asyncio
async def test_first_view_increments_but_owner_view_does_not():
    viewer = make_user()
    listing = make_listing(uuid.uuid4(), views=8)
    session = FakeSession(listing=listing, scalars=[listing, uuid.uuid4(), 0, None])
    result = await record_listing_view(listing.id, viewer, session)
    assert result.view_recorded is True
    assert result.views_count == 9

    owner_listing = make_listing(viewer.id, views=9)
    owner_session = FakeSession(listing=owner_listing, scalars=[owner_listing, 0, None])
    owner_result = await record_listing_view(owner_listing.id, viewer, owner_session)
    assert owner_result.view_recorded is False
    assert owner_result.views_count == 9


@pytest.mark.asyncio
async def test_recent_view_does_not_increment_and_expired_view_does():
    viewer = make_user()
    recent_listing = make_listing(uuid.uuid4(), views=3)
    recent_view = ListingView(listing_id=recent_listing.id, user_id=viewer.id, viewed_at=datetime.now(UTC) - timedelta(hours=1))
    recent_session = FakeSession(listing=recent_listing, scalars=[recent_listing, None, recent_view, 0, None])
    recent_result = await record_listing_view(recent_listing.id, viewer, recent_session)
    assert recent_result.view_recorded is False
    assert recent_result.views_count == 3

    expired_listing = make_listing(uuid.uuid4(), views=3)
    expired_view = ListingView(listing_id=expired_listing.id, user_id=viewer.id, viewed_at=datetime.now(UTC) - timedelta(hours=25))
    expired_session = FakeSession(listing=expired_listing, scalars=[expired_listing, None, expired_view, 0, None])
    expired_result = await record_listing_view(expired_listing.id, viewer, expired_session)
    assert expired_result.view_recorded is True
    assert expired_result.views_count == 4
    assert expired_view.viewed_at > datetime.now(UTC) - timedelta(minutes=1)


@pytest.mark.asyncio
async def test_like_and_unlike_return_server_confirmed_state():
    viewer = make_user()
    listing = make_listing(uuid.uuid4())
    like_session = FakeSession(listing=listing, scalars=[1, uuid.uuid4()])
    liked = await like_listing(listing.id, viewer, like_session)
    assert liked.likes_count == 1
    assert liked.liked_by_me is True
    assert like_session.commits == 1

    unlike_session = FakeSession(listing=listing, scalars=[0, None])
    unliked = await unlike_listing(listing.id, viewer, unlike_session)
    assert unliked.likes_count == 0
    assert unliked.liked_by_me is False
    assert unlike_session.commits == 1
