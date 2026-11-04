"""holerite ligado a rendas, rotulos aprendidos e saldo do FGTS

Revision ID: c7a9d2e4f611
Revises: b5e8f1a2c3d4
"""
from alembic import op
import sqlalchemy as sa

revision = 'c7a9d2e4f611'
down_revision = 'b5e8f1a2c3d4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('payslips', sa.Column('links', sa.JSON(), server_default='[]', nullable=False))
    op.create_table(
        'payslip_labels',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('label', sa.String(length=60), nullable=False),
        sa.Column('field', sa.String(length=30), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('label'),
    )
    op.create_table(
        'fgts_balances',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('owner_user_id', sa.Integer(), nullable=False),
        sa.Column('hidden', sa.Boolean(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('balance_cents', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['owner_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_fgts_balances_owner_user_id', 'fgts_balances', ['owner_user_id'])


def downgrade() -> None:
    op.drop_index('ix_fgts_balances_owner_user_id', table_name='fgts_balances')
    op.drop_table('fgts_balances')
    op.drop_table('payslip_labels')
    op.drop_column('payslips', 'links')
