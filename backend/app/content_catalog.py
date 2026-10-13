"""Publication identity and per-account catalogue baselines; no localStorage state."""
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from .models import ContentSeenState, Listing, TrainingProduct, User


def catalogue(section):
    if section == "training":
        return TrainingProduct, (TrainingProduct.published.is_(True), TrainingProduct.deleted_at.is_(None))
    return Listing, (Listing.listing_type == "unique", Listing.status.in_(("active", "reserved")), Listing.deleted_at.is_(None))


async def next_publication_revision(session):
    # Sequences alone are not commit-ordered: a slow revision N could become
    # visible after a reader has acknowledged N+1. Serialize publication writers
    # until commit; readers still use ordinary MVCC and never wait on this lock.
    await session.execute(text("SELECT pg_advisory_xact_lock(74190828)"))
    return await session.scalar(select(func.nextval("content_publication_revision_seq")))


async def initialize_content_seen(session, user_id):
    existing = set((await session.scalars(select(ContentSeenState.section).where(ContentSeenState.user_id == user_id))).all())
    if existing == {"unique", "training"}:
        return
    await session.scalar(select(User.id).where(User.id == user_id).with_for_update(key_share=True))
    for section in {"unique", "training"} - existing:
        model, visible = catalogue(section)
        marker = int(await session.scalar(select(func.coalesce(func.max(model.content_revision), 0)).where(*visible)) or 0)
        await session.execute(insert(ContentSeenState).values(user_id=user_id, section=section, last_seen_revision=marker)
            .on_conflict_do_nothing(index_elements=[ContentSeenState.user_id, ContentSeenState.section]))
    await session.commit()
