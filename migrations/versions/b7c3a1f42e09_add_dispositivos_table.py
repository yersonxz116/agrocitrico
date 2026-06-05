"""add dispositivos table and link lecturas_sensor

Revision ID: b7c3a1f42e09
Revises: 46958d83b632
Create Date: 2026-06-05 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7c3a1f42e09'
down_revision = '46958d83b632'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('dispositivos',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('nombre', sa.String(length=120), nullable=False),
        sa.Column('token', sa.String(length=64), nullable=False),
        sa.Column('activo', sa.Boolean(), nullable=False, server_default=sa.text('1')),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_dispositivos_user_id', 'dispositivos', ['user_id'])
    op.create_index('ix_dispositivos_token', 'dispositivos', ['token'], unique=True)

    with op.batch_alter_table('lecturas_sensor', schema=None) as batch_op:
        batch_op.add_column(sa.Column('dispositivo_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_lectura_dispositivo', 'dispositivos', ['dispositivo_id'], ['id'])
        batch_op.create_index('ix_lecturas_sensor_dispositivo_id', ['dispositivo_id'])


def downgrade():
    with op.batch_alter_table('lecturas_sensor', schema=None) as batch_op:
        batch_op.drop_index('ix_lecturas_sensor_dispositivo_id')
        batch_op.drop_constraint('fk_lectura_dispositivo', type_='foreignkey')
        batch_op.drop_column('dispositivo_id')

    op.drop_index('ix_dispositivos_token', table_name='dispositivos')
    op.drop_index('ix_dispositivos_user_id', table_name='dispositivos')
    op.drop_table('dispositivos')
