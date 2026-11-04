"""tag nas dividas

Revision ID: 7c1d2e9a4f30
Revises: 4088e776b6ed
"""
from alembic import op
import sqlalchemy as sa

revision = '7c1d2e9a4f30'
down_revision = '4088e776b6ed'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('debts', sa.Column('category_id', sa.Integer(), nullable=True))
    op.create_foreign_key('debts_category_id_fkey', 'debts', 'categories', ['category_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    op.drop_constraint('debts_category_id_fkey', 'debts', type_='foreignkey')
    op.drop_column('debts', 'category_id')
