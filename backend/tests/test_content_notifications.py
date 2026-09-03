import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.models import ContentSeenState, TrainingProduct, TrainingView, User
from app.routes import content_unseen_section, mark_content_seen, record_training_view
from app.schemas import ContentMarkSeenCreate


class FakeSession:
    def __init__(self, scalars):
        self.scalars = list(scalars)
        self.executed = []
        self.added = []
        self.commits = 0

    async def scalar(self, _statement):
        return self.scalars.pop(0)

    async def execute(self, statement):
        self.executed.append(statement)

    def add(self, value):
        self.added.append(value)

    async def commit(self):
        self.commits += 1


def make_user(role="user"):
    return User(id=uuid.uuid4(), telegram_id=123, first_name="User", role=role)


def make_training(admin_id, views=0):
    return TrainingProduct(
        id=uuid.uuid4(), admin_id=admin_id, title="Course", short_description="Short",
        full_description="Full", cover_url="/cover", product_type="personal",
        price_af_coins=10, availability="available", published=True, pinned=False,
        views_count=views, content_revision=3, published_at=datetime.now(UTC),
    )


def test_seen_and_training_view_tables_are_personal_and_deduplicated():
    seen_unique = next(item for item in ContentSeenState.__table__.constraints if item.name == "uq_content_seen_user_section")
    view_unique = next(item for item in TrainingView.__table__.constraints if item.name == "uq_training_view_product_user")
    assert [column.name for column in seen_unique.columns] == ["user_id", "section"]
    assert [column.name for column in view_unique.columns] == ["product_id", "user_id"]


@pytest.mark.asyncio
async def test_unseen_count_uses_each_users_own_revision():
    user_a = make_user()
    user_b = make_user()
    state_a = ContentSeenState(user_id=user_a.id, section="training", last_seen_revision=2)
    state_b = ContentSeenState(user_id=user_b.id, section="training", last_seen_revision=0)
    result_a = await content_unseen_section(FakeSession([state_a, 3, 1]), user_a.id, "training")
    result_b = await content_unseen_section(FakeSession([state_b, 3, 3]), user_b.id, "training")
    assert result_a == {"unseen_count": 1, "marker": 3}
    assert result_b == {"unseen_count": 3, "marker": 3}


@pytest.mark.asyncio
async def test_mark_seen_keeps_the_received_marker_when_newer_content_exists():
    user = make_user()
    # First snapshot says revision 4 now exists, but the browser only received marker 3.
    # The response therefore still reports revision 4 as unseen.
    session = FakeSession([None, 4, 4, ContentSeenState(user_id=user.id, section="training", last_seen_revision=3), 4, 1])
    result = await mark_content_seen("training", ContentMarkSeenCreate(marker=3), user, session)
    assert result == {"unseen_count": 1, "marker": 4}
    assert session.commits == 1
    assert len(session.executed) == 1


@pytest.mark.asyncio
async def test_training_view_matches_listing_24_hour_deduplication():
    viewer = make_user()
    product = make_training(uuid.uuid4(), views=7)
    first = FakeSession([product, uuid.uuid4()])
    result = await record_training_view(product.id, viewer, first)
    assert result.views_count == 8 and result.view_recorded is True

    recent = TrainingView(product_id=product.id, user_id=viewer.id, viewed_at=datetime.now(UTC) - timedelta(hours=1))
    repeated = FakeSession([product, None, recent])
    result = await record_training_view(product.id, viewer, repeated)
    assert result.views_count == 8 and result.view_recorded is False

