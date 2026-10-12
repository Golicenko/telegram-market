"""SQLite is used for persistence tests only, never sequence/concurrency proof."""
from sqlalchemy import event, select, func
from app.models import WithdrawalRequest


@event.listens_for(WithdrawalRequest, "before_insert")
def sqlite_test_number(mapper, connection, target):
    # SQLite ignores Identity on non-PK columns. Production PostgreSQL uses its
    # real non-transactional sequence; separate PG tests verify that behaviour.
    if connection.dialect.name == "sqlite" and target.public_number is None:
        target.public_number = connection.scalar(select(func.coalesce(func.max(WithdrawalRequest.public_number), 0))) + 1
