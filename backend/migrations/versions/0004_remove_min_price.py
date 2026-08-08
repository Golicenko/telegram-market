from alembic import op

revision = "0004_remove_min_price"
down_revision = "0003_payments_support"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint(
        "ck_listings_min_price",
        "listings",
        type_="check",
    )

    op.create_check_constraint(
        "ck_listings_min_price",
        "listings",
        "price_af_coins >= 0",
    )


def downgrade():
    op.drop_constraint(
        "ck_listings_min_price",
        "listings",
        type_="check",
    )

    op.create_check_constraint(
        "ck_listings_min_price",
        "listings",
        "price_af_coins >= 100",
    )
