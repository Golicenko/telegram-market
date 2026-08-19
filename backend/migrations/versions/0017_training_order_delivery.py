"""Track personal-order notification delivery and widen training text fields.

Revision ID: 0017_training_delivery
Revises: 0016_deal_support
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0017_training_delivery"
down_revision: str | None = "0016_deal_support"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("training_products", "title", existing_type=sa.String(length=180), type_=sa.Text(), existing_nullable=False)
    op.alter_column("training_products", "short_description", existing_type=sa.String(length=360), type_=sa.Text(), existing_nullable=False)
    op.alter_column("training_materials", "title", existing_type=sa.String(length=180), type_=sa.Text(), existing_nullable=False)
    op.alter_column("training_purchases", "title_snapshot", existing_type=sa.String(length=180), type_=sa.Text(), existing_nullable=False)

    op.add_column("training_purchases", sa.Column("payment_status", sa.String(16), nullable=False, server_default="paid"))
    op.add_column(
        "training_purchases",
        sa.Column("admin_notification_status", sa.String(24), nullable=False, server_default="not_required"),
    )
    op.add_column(
        "training_purchases",
        sa.Column("admin_notification_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("training_purchases", sa.Column("admin_notification_error", sa.Text(), nullable=True))
    op.add_column("training_purchases", sa.Column("admin_notification_last_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("training_purchases", sa.Column("admin_notified_at", sa.DateTime(timezone=True), nullable=True))
    # Delivery of historical notifications cannot be proven. Mark them failed
    # for an explicit manual retry instead of flooding administrators on deploy.
    op.execute(
        "UPDATE training_purchases SET admin_notification_status = 'failed', "
        "admin_notification_error = 'Статус доставки уведомления до обновления неизвестен' "
        "WHERE product_type = 'personal'"
    )
    op.create_index("ix_training_purchases_payment_status", "training_purchases", ["payment_status"])
    op.create_index(
        "ix_training_purchases_admin_notification_status",
        "training_purchases",
        ["admin_notification_status"],
    )
    op.create_check_constraint(
        "ck_training_purchases_payment_status",
        "training_purchases",
        "payment_status = 'paid'",
    )
    op.create_check_constraint(
        "ck_training_purchases_admin_notification_status",
        "training_purchases",
        "admin_notification_status IN ('pending','sending','sent','failed','not_required')",
    )
    op.create_check_constraint(
        "ck_training_purchases_admin_notification_attempts",
        "training_purchases",
        "admin_notification_attempts >= 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_training_purchases_admin_notification_attempts", "training_purchases", type_="check")
    op.drop_constraint("ck_training_purchases_admin_notification_status", "training_purchases", type_="check")
    op.drop_constraint("ck_training_purchases_payment_status", "training_purchases", type_="check")
    op.drop_index("ix_training_purchases_admin_notification_status", table_name="training_purchases")
    op.drop_index("ix_training_purchases_payment_status", table_name="training_purchases")
    op.drop_column("training_purchases", "admin_notified_at")
    op.drop_column("training_purchases", "admin_notification_last_attempt_at")
    op.drop_column("training_purchases", "admin_notification_error")
    op.drop_column("training_purchases", "admin_notification_attempts")
    op.drop_column("training_purchases", "admin_notification_status")
    op.drop_column("training_purchases", "payment_status")
    # Text fields, including title_snapshot, intentionally remain widened: narrowing them could truncate
    # administrator content created after this migration.
