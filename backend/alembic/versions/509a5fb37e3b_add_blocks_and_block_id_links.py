"""add blocks and block_id links

Revision ID: 509a5fb37e3b
Revises: 32a030ba8bc4
Create Date: 2026-07-19 19:13:12.751236

Purely ADDITIVE: one new table plus three nullable FK columns. Nothing is dropped,
renamed, or rewritten, and the existing free-text `field_block` column is deliberately
left untouched and un-backfilled — inferring block identity from grower shorthand would
fabricate structure nobody recorded.

SQLite cannot ALTER in place, so the three `add_column` steps rewrite their tables via
batch mode (env.py sets render_as_batch=True). Back up a populated pilot database before
running this.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '509a5fb37e3b'
down_revision: Union[str, Sequence[str], None] = '32a030ba8bc4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Named explicitly: autogenerate emits None, which SQLite cannot drop by name on the
# way back down.
_BLOCK_FKS = (
    ("planned_sprays", "fk_planned_sprays_block_id_blocks"),
    ("scout_observations", "fk_scout_observations_block_id_blocks"),
    ("spray_events", "fk_spray_events_block_id_blocks"),
)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'blocks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('farm_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('crop', sa.String(length=100), nullable=True),
        sa.Column('cultivar', sa.String(length=120), nullable=True),
        sa.Column('area', sa.Float(), nullable=True),
        sa.Column('area_unit', sa.String(length=10), nullable=True),
        sa.Column('planting_date', sa.Date(), nullable=True),
        sa.Column('expected_harvest_date', sa.Date(), nullable=True),
        sa.Column('phenology_stage', sa.String(length=60), nullable=True),
        sa.Column('phenology_observed_on', sa.Date(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('data_source', sa.String(length=40), nullable=True),
        sa.Column('data_confidence', sa.String(length=40), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['farm_id'], ['farms.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('blocks', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_blocks_farm_id'), ['farm_id'], unique=False)

    for table, fk_name in _BLOCK_FKS:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(sa.Column('block_id', sa.Integer(), nullable=True))
            batch_op.create_index(
                batch_op.f(f'ix_{table}_block_id'), ['block_id'], unique=False
            )
            batch_op.create_foreign_key(fk_name, 'blocks', ['block_id'], ['id'])


def downgrade() -> None:
    """Downgrade schema.

    Batch mode recreates each table from the remaining columns, so dropping `block_id`
    removes its foreign key with it — no explicit drop_constraint (autogenerate emits
    `drop_constraint(None, ...)`, which SQLite cannot resolve).
    """
    for table, _fk_name in reversed(_BLOCK_FKS):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_index(batch_op.f(f'ix_{table}_block_id'))
            batch_op.drop_column('block_id')

    with op.batch_alter_table('blocks', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_blocks_farm_id'))
    op.drop_table('blocks')
