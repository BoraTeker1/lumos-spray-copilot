"""add pca credentials and farm authorizations

Revision ID: fd3e65674140
Revises: 509a5fb37e3b
Create Date: 2026-07-19 19:20:44.976948

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fd3e65674140'
down_revision: Union[str, Sequence[str], None] = '509a5fb37e3b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Additive. Note `pca_credentials.token_hash` is UNIQUE and holds only a sha256
    digest — the plaintext token is shown once at issuance and never stored, so this
    table leaking does not yield usable credentials.
    """
    op.create_table('pca_credentials',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('display_name', sa.String(length=120), nullable=False),
    sa.Column('license_identifier', sa.String(length=60), nullable=False),
    sa.Column('license_state', sa.String(length=2), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('token_prefix', sa.String(length=12), nullable=True),
    sa.Column('issued_by', sa.String(length=120), nullable=True),
    sa.Column('active_from', sa.Date(), nullable=True),
    sa.Column('active_to', sa.Date(), nullable=True),
    sa.Column('revoked_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('pca_credentials', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_pca_credentials_token_hash'), ['token_hash'], unique=True)

    op.create_table('pca_farm_authorizations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('pca_credential_id', sa.Integer(), nullable=False),
    sa.Column('farm_id', sa.Integer(), nullable=False),
    sa.Column('granted_on', sa.Date(), nullable=True),
    sa.Column('granted_by', sa.String(length=120), nullable=True),
    sa.Column('revoked_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['farm_id'], ['farms.id'], ),
    sa.ForeignKeyConstraint(['pca_credential_id'], ['pca_credentials.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('pca_farm_authorizations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_pca_farm_authorizations_farm_id'), ['farm_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_pca_farm_authorizations_pca_credential_id'), ['pca_credential_id'], unique=False)

    with op.batch_alter_table('planned_sprays', schema=None) as batch_op:
        batch_op.add_column(sa.Column('reviewed_by_credential_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_planned_sprays_reviewed_by_credential_id_pca_credentials',
            'pca_credentials', ['reviewed_by_credential_id'], ['id'],
        )


def downgrade() -> None:
    """Downgrade schema.

    Batch mode rebuilds each table, so dropping the column drops its foreign key with
    it — autogenerate's `drop_constraint(None, ...)` cannot be resolved by SQLite.
    """
    with op.batch_alter_table('planned_sprays', schema=None) as batch_op:
        batch_op.drop_column('reviewed_by_credential_id')

    with op.batch_alter_table('pca_farm_authorizations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_pca_farm_authorizations_pca_credential_id'))
        batch_op.drop_index(batch_op.f('ix_pca_farm_authorizations_farm_id'))

    op.drop_table('pca_farm_authorizations')
    with op.batch_alter_table('pca_credentials', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_pca_credentials_token_hash'))

    op.drop_table('pca_credentials')
    # ### end Alembic commands ###
