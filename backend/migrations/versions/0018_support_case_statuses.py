"""Use explicit new/in-progress/resolved states for deal support cases.

Revision ID: 0018_support_statuses
Revises: 0017_training_delivery
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0018_support_statuses"
down_revision: str | None = "0017_training_delivery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Keep legacy general tickets intact while normalizing deal SupportCases.
    op.drop_index("uq_support_active_deal", table_name="support_tickets")
    op.drop_constraint("ck_support_ticket_status", "support_tickets", type_="check")
    op.execute("UPDATE support_tickets SET status = 'new' WHERE case_type = 'deal' AND status = 'open'")
    op.create_check_constraint(
        "ck_support_ticket_status",
        "support_tickets",
        "status IN ('new','open','in_progress','resolved','closed')",
    )
    op.create_index(
        "uq_support_active_deal",
        "support_tickets",
        ["deal_id"],
        unique=True,
        postgresql_where=sa.text("case_type = 'deal' AND status IN ('new','open','in_progress')"),
    )


def downgrade() -> None:
    op.drop_index("uq_support_active_deal", table_name="support_tickets")
    op.drop_constraint("ck_support_ticket_status", "support_tickets", type_="check")
    op.execute("UPDATE support_tickets SET status = 'open' WHERE status = 'new'")
    op.create_check_constraint(
        "ck_support_ticket_status",
        "support_tickets",
        "status IN ('open','in_progress','resolved','closed')",
    )
    op.create_index(
        "uq_support_active_deal",
        "support_tickets",
        ["deal_id"],
        unique=True,
        postgresql_where=sa.text("case_type = 'deal' AND status IN ('open','in_progress')"),
    )
