"""Stable withdrawal numbers and linked support, without changing money."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0045_withdrawal_public_numbers"
down_revision = "0044_admin_balance_idempotency"
branch_labels = None
depends_on = None


def upgrade():
    # Block inserts during backfill. Every status participates; gaps after rollback
    # are intentional because PostgreSQL sequences never roll nextval back.
    op.execute("LOCK TABLE withdrawal_requests IN ACCESS EXCLUSIVE MODE")
    op.add_column("withdrawal_requests", sa.Column("public_number", sa.BigInteger()))
    op.execute("""WITH numbered AS (
        SELECT id, row_number() OVER (ORDER BY created_at ASC NULLS LAST, id) AS n
        FROM withdrawal_requests
    ) UPDATE withdrawal_requests w SET public_number = n FROM numbered WHERE w.id = numbered.id""")
    op.alter_column("withdrawal_requests", "public_number", nullable=False)
    op.execute("ALTER TABLE withdrawal_requests ALTER COLUMN public_number ADD GENERATED ALWAYS AS IDENTITY")
    op.execute("""SELECT setval(pg_get_serial_sequence('withdrawal_requests','public_number'),
        COALESCE((SELECT max(public_number) FROM withdrawal_requests), 1),
        EXISTS(SELECT 1 FROM withdrawal_requests))""")
    op.create_unique_constraint("uq_withdrawal_public_number", "withdrawal_requests", ["public_number"])
    op.add_column("withdrawal_requests", sa.Column("cancelled_at", sa.DateTime(timezone=True)))
    op.add_column("withdrawal_requests", sa.Column("payout_reference", sa.String(200)))
    op.add_column("support_tickets", sa.Column("withdrawal_id", postgresql.UUID(as_uuid=True),
        sa.ForeignKey("withdrawal_requests.id", ondelete="RESTRICT")))
    op.create_unique_constraint("uq_support_withdrawal", "support_tickets", ["withdrawal_id"])


def downgrade():
    # These identifiers may already have been communicated to customers. A code
    # rollback must retain them and their sequence; never silently reuse numbers.
    raise RuntimeError("Keep withdrawal public numbers on rollback; use a forward migration.")
