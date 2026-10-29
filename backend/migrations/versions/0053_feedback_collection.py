"""Voluntary feedback, explicit publication consent and at-most-once delivery."""
from alembic import op

revision = "0053_feedback_collection"
down_revision = "0052_gift_delivery_progress"
branch_labels = None
depends_on = None


def upgrade():
    statements = """CREATE TABLE feedback_campaigns (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(), admin_id UUID NOT NULL REFERENCES users(id),
        client_request_id UUID NOT NULL UNIQUE, status VARCHAR(16) NOT NULL DEFAULT 'queued',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(), completed_at TIMESTAMPTZ,
        CONSTRAINT ck_feedback_campaign_status CHECK(status IN ('queued','running','completed','stopped')));
        CREATE UNIQUE INDEX uq_feedback_active_campaign ON feedback_campaigns ((true)) WHERE status IN ('queued','running');
        CREATE TABLE feedback_requests (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(), campaign_id UUID NOT NULL REFERENCES feedback_campaigns(id),
        user_id UUID NOT NULL REFERENCES users(id), telegram_id BIGINT NOT NULL,
        status VARCHAR(16) NOT NULL DEFAULT 'pending', invitation_message_id BIGINT, prompt_message_id BIGINT,
        error_type VARCHAR(64), created_at TIMESTAMPTZ NOT NULL DEFAULT now(), expires_at TIMESTAMPTZ NOT NULL,
        started_at TIMESTAMPTZ, sent_at TIMESTAMPTZ,
        CONSTRAINT uq_feedback_campaign_user UNIQUE(campaign_id,user_id),
        CONSTRAINT ck_feedback_request_status CHECK(status IN ('pending','sending','sent','waiting','received','declined','failed','expired','cancelled')));
        CREATE INDEX ix_feedback_requests_campaign_id ON feedback_requests(campaign_id);
        CREATE INDEX ix_feedback_requests_user_id ON feedback_requests(user_id);
        CREATE INDEX ix_feedback_request_queue ON feedback_requests(status,created_at);
        CREATE UNIQUE INDEX uq_feedback_active_user ON feedback_requests(user_id) WHERE status IN ('pending','sending','sent','waiting');
        CREATE TABLE user_feedback (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(), request_id UUID NOT NULL UNIQUE REFERENCES feedback_requests(id),
        user_id UUID NOT NULL REFERENCES users(id), telegram_chat_id BIGINT NOT NULL, telegram_message_id BIGINT NOT NULL,
        telegram_update_id BIGINT NOT NULL UNIQUE, text TEXT NOT NULL, protected BOOLEAN NOT NULL DEFAULT false,
        consent VARCHAR(16) NOT NULL DEFAULT 'pending', consent_at TIMESTAMPTZ, consent_version INTEGER NOT NULL DEFAULT 0,
        seen_at TIMESTAMPTZ, seen_by UUID REFERENCES users(id), created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_feedback_original_message UNIQUE(telegram_chat_id,telegram_message_id),
        CONSTRAINT ck_feedback_consent CHECK(consent IN ('pending','allowed','private')));
        CREATE INDEX ix_user_feedback_created_at ON user_feedback(created_at);
        CREATE TABLE feedback_deliveries (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(), request_id UUID NOT NULL REFERENCES feedback_requests(id),
        feedback_id UUID REFERENCES user_feedback(id), target_telegram_id BIGINT NOT NULL, kind VARCHAR(32) NOT NULL,
        dedup_key VARCHAR(128) NOT NULL UNIQUE, status VARCHAR(16) NOT NULL DEFAULT 'pending', message_id BIGINT,
        error_type VARCHAR(64), created_at TIMESTAMPTZ NOT NULL DEFAULT now(), started_at TIMESTAMPTZ,
        CONSTRAINT ck_feedback_delivery_status CHECK(status IN ('pending','sending','sent','failed','cancelled')));
        CREATE INDEX ix_feedback_delivery_queue ON feedback_deliveries(status,created_at);
    """
    for statement in statements.split(";"):
        if statement.strip():
            op.execute(statement)


def downgrade():
    raise RuntimeError("Keep feedback and consent evidence. Roll back application code without dropping these tables.")
