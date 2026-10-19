"""in-app notifications + ancillary result attachments

Revision ID: b8e4d1a7c3f2
Revises: e5b7c1d9a3f4
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "b8e4d1a7c3f2"
down_revision = "e5b7c1d9a3f4"
branch_labels = None
depends_on = None

_TS = sa.DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql")


def upgrade() -> None:
    op.create_table(
        "service_result_attachments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("service_request_id", sa.String(36), sa.ForeignKey("service_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("service_result_id", sa.String(36), sa.ForeignKey("service_results.id", ondelete="CASCADE"), nullable=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("file_object_key", sa.String(512), nullable=True),
        sa.Column("file_sha256", sa.String(64), nullable=True),
        sa.Column("file_bytes", sa.Integer, nullable=True),
        sa.Column("file_mime", sa.String(128), nullable=True),
        sa.Column("uploaded_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", _TS, nullable=True),
    )
    op.create_index("ix_service_result_attachments_service_request_id", "service_result_attachments", ["service_request_id"])
    op.create_index("ix_service_result_attachments_service_result_id", "service_result_attachments", ["service_result_id"])
    op.create_index("ix_service_result_attachments_uploaded_by", "service_result_attachments", ["uploaded_by"])

    op.create_table(
        "notifications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("facility_name", sa.String(255), nullable=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.String(500), nullable=True),
        sa.Column("link", sa.String(255), nullable=True),
        sa.Column("urgent", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", _TS, nullable=True),
        sa.Column("read_at", _TS, nullable=True),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"])


def downgrade() -> None:
    op.drop_table("notifications")
    op.drop_table("service_result_attachments")
