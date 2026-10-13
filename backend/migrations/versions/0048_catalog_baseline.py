"""Reset legacy false badges without deleting content or user history."""
from alembic import op

revision = "0048_catalog_baseline"
down_revision = "0047_analytics_observations"
branch_labels = None
depends_on = None


def upgrade():
    # Migration executes before new code. Prevent legacy writers from allocating
    # a publication between the baseline queries and committing the reset.
    op.execute("LOCK TABLE listings, training_products IN SHARE ROW EXCLUSIVE MODE")
    op.execute("""
        INSERT INTO content_seen_states(id, user_id, section, last_seen_revision)
        SELECT md5(u.id::text || ':' || s.section)::uuid, u.id, s.section,
          CASE WHEN s.section = 'unique' THEN
            (SELECT COALESCE(MAX(content_revision), 0) FROM listings
             WHERE listing_type = 'unique' AND status IN ('active','reserved') AND deleted_at IS NULL)
          ELSE
            (SELECT COALESCE(MAX(content_revision), 0) FROM training_products
             WHERE published IS TRUE AND deleted_at IS NULL)
          END
        FROM users u CROSS JOIN (VALUES ('unique'), ('training')) s(section)
        WHERE u.mini_app_last_active_at IS NOT NULL
           OR EXISTS (SELECT 1 FROM content_seen_states c WHERE c.user_id = u.id)
        ON CONFLICT (user_id, section) DO UPDATE
          SET last_seen_revision = GREATEST(content_seen_states.last_seen_revision, EXCLUDED.last_seen_revision),
              updated_at = now()
    """)


def downgrade():
    # Baselines cannot be reconstructed; preserving them is safer than restoring
    # false unread badges. There is no schema change to undo.
    pass
