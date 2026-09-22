"""Label existing cars CP1; require an explicit game for every new listing."""
from alembic import op
import sqlalchemy as sa

revision = "0040_listing_game_version"
down_revision = "0039_car_sale_zero_fee"
branch_labels = None
depends_on = None


def upgrade():
    # The temporary default backfills ALL existing rows, including sold/hidden
    # listings. PostgreSQL applies this DDL in the existing migration transaction.
    op.add_column("listings", sa.Column(
        "game_version", sa.String(24), nullable=False,
        server_default=sa.text("'car_parking_1'"),
    ))
    op.create_check_constraint(
        "ck_listings_game_version", "listings",
        "game_version IN ('car_parking_1','car_parking_2')",
    )
    # No persistent default: new writes must choose the game, even outside API.
    op.alter_column("listings", "game_version", server_default=None)


def downgrade():
    # Never silently lose the game identity of cars that were already published.
    raise RuntimeError("Game identity must be preserved; use a forward migration instead of dropping game_version.")
