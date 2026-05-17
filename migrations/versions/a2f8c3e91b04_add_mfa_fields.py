"""add mfa fields

Revision ID: a2f8c3e91b04
Revises: d1ba8446358a
Create Date: 2026-05-17 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "a2f8c3e91b04"
down_revision = "d1ba8446358a"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("mfa_enabled", sa.Boolean(), nullable=False, server_default=sa.text("0")))
    op.add_column("users", sa.Column("totp_secret", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("pem_fingerprint", sa.String(length=64), nullable=True))
    op.add_column("users", sa.Column("pem_public_key", sa.Text(), nullable=True))

    op.create_table(
        "backup_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("code_hash", sa.String(length=255), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_backup_codes_user_id", "backup_codes", ["user_id"])


def downgrade():
    op.drop_index("ix_backup_codes_user_id", table_name="backup_codes")
    op.drop_table("backup_codes")
    op.drop_column("users", "pem_public_key")
    op.drop_column("users", "pem_fingerprint")
    op.drop_column("users", "totp_secret")
    op.drop_column("users", "mfa_enabled")
