"""holerites

Revision ID: b5e8f1a2c3d4
Revises: 7c1d2e9a4f30
"""
from alembic import op
import sqlalchemy as sa

revision = 'b5e8f1a2c3d4'
down_revision = '7c1d2e9a4f30'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'payslips',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('owner_user_id', sa.Integer(), nullable=False),
        sa.Column('hidden', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('company', sa.String(length=160), nullable=False),
        sa.Column('cnpj', sa.String(length=20), nullable=False),
        sa.Column('reference_month', sa.Integer(), nullable=False),
        sa.Column('gross_cents', sa.BigInteger(), nullable=False),
        sa.Column('deductions_cents', sa.BigInteger(), nullable=False),
        sa.Column('net_cents', sa.BigInteger(), nullable=False),
        sa.Column('base_salary_cents', sa.BigInteger(), nullable=True),
        sa.Column('inss_base_cents', sa.BigInteger(), nullable=True),
        sa.Column('fgts_base_cents', sa.BigInteger(), nullable=True),
        sa.Column('fgts_cents', sa.BigInteger(), nullable=True),
        sa.Column('irrf_base_cents', sa.BigInteger(), nullable=True),
        sa.Column('items', sa.JSON(), nullable=False),
        sa.Column('transaction_id', sa.Integer(), nullable=True),
        sa.Column('fingerprint', sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(['owner_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('owner_user_id', 'fingerprint'),
    )
    op.create_index('ix_payslips_owner_user_id', 'payslips', ['owner_user_id'])


def downgrade() -> None:
    op.drop_index('ix_payslips_owner_user_id', table_name='payslips')
    op.drop_table('payslips')
