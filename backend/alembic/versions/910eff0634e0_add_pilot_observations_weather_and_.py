"""add pilot observations weather and scouting samples

Revision ID: 910eff0634e0
Revises: fd3e65674140
Create Date: 2026-07-19 19:31:08.072124

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '910eff0634e0'
down_revision: Union[str, Sequence[str], None] = 'fd3e65674140'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Additive. `uq_weather_observation_station_hour` is a PARTIAL unique index
    (supersedes_id IS NULL): at most one *original* reading per station per timestamp,
    while still allowing a correction to repeat that station+timestamp on the row that
    supersedes it. A plain unique index would make the append-only correction path
    impossible.
    """
    op.create_table('scouting_samples',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('farm_id', sa.Integer(), nullable=False),
    sa.Column('block_id', sa.Integer(), nullable=False),
    sa.Column('observed_at', sa.DateTime(), nullable=False),
    sa.Column('recorded_at', sa.DateTime(), nullable=False),
    sa.Column('method', sa.String(length=40), nullable=False),
    sa.Column('target', sa.String(length=200), nullable=False),
    sa.Column('units_inspected', sa.Integer(), nullable=False),
    sa.Column('units_affected', sa.Integer(), nullable=False),
    sa.Column('incidence_pct', sa.Float(), nullable=True),
    sa.Column('severity_index', sa.Float(), nullable=True),
    sa.Column('severity_scale', sa.String(length=40), nullable=True),
    sa.Column('scout_name', sa.String(length=120), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('source_type', sa.String(length=40), nullable=False),
    sa.Column('source_reference', sa.String(length=255), nullable=True),
    sa.Column('external_record_id', sa.String(length=120), nullable=True),
    sa.Column('supersedes_id', sa.Integer(), nullable=True),
    sa.Column('data_source', sa.String(length=40), nullable=True),
    sa.Column('data_confidence', sa.String(length=40), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['block_id'], ['blocks.id'], ),
    sa.ForeignKeyConstraint(['farm_id'], ['farms.id'], ),
    sa.ForeignKeyConstraint(['supersedes_id'], ['scouting_samples.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('scouting_samples', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_scouting_samples_block_id'), ['block_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_scouting_samples_farm_id'), ['farm_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_scouting_samples_observed_at'), ['observed_at'], unique=False)

    op.create_table('weather_observations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('farm_id', sa.Integer(), nullable=False),
    sa.Column('block_id', sa.Integer(), nullable=True),
    sa.Column('station_id', sa.String(length=80), nullable=False),
    sa.Column('station_name', sa.String(length=160), nullable=True),
    sa.Column('station_distance_km', sa.Float(), nullable=True),
    sa.Column('observed_at', sa.DateTime(), nullable=False),
    sa.Column('recorded_at', sa.DateTime(), nullable=False),
    sa.Column('temperature_c', sa.Float(), nullable=True),
    sa.Column('relative_humidity_pct', sa.Float(), nullable=True),
    sa.Column('rainfall_mm', sa.Float(), nullable=True),
    sa.Column('leaf_wetness_minutes', sa.Float(), nullable=True),
    sa.Column('wetness_is_measured', sa.Boolean(), nullable=True),
    sa.Column('source_type', sa.String(length=40), nullable=False),
    sa.Column('source_reference', sa.String(length=255), nullable=True),
    sa.Column('quality_flag', sa.String(length=60), nullable=True),
    sa.Column('supersedes_id', sa.Integer(), nullable=True),
    sa.Column('data_source', sa.String(length=40), nullable=True),
    sa.Column('data_confidence', sa.String(length=40), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['block_id'], ['blocks.id'], ),
    sa.ForeignKeyConstraint(['farm_id'], ['farms.id'], ),
    sa.ForeignKeyConstraint(['supersedes_id'], ['weather_observations.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('weather_observations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_weather_observations_block_id'), ['block_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_weather_observations_farm_id'), ['farm_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_weather_observations_observed_at'), ['observed_at'], unique=False)
        batch_op.create_index('uq_weather_observation_station_hour', ['station_id', 'observed_at'], unique=True, sqlite_where=sa.text('supersedes_id IS NULL'))

    with op.batch_alter_table('pilot_import_batches', schema=None) as batch_op:
        # server_default is REQUIRED here: the model's `default=0` is applied in
        # Python, so a NOT NULL column added to a table that already has import
        # batches would fail with no default at the database level.
        batch_op.add_column(sa.Column(
            'weather_observation_count', sa.Integer(), nullable=False,
            server_default='0',
        ))
        batch_op.add_column(sa.Column(
            'scouting_sample_count', sa.Integer(), nullable=False, server_default='0',
        ))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('pilot_import_batches', schema=None) as batch_op:
        batch_op.drop_column('scouting_sample_count')
        batch_op.drop_column('weather_observation_count')

    with op.batch_alter_table('weather_observations', schema=None) as batch_op:
        batch_op.drop_index('uq_weather_observation_station_hour', sqlite_where=sa.text('supersedes_id IS NULL'))
        batch_op.drop_index(batch_op.f('ix_weather_observations_observed_at'))
        batch_op.drop_index(batch_op.f('ix_weather_observations_farm_id'))
        batch_op.drop_index(batch_op.f('ix_weather_observations_block_id'))

    op.drop_table('weather_observations')
    with op.batch_alter_table('scouting_samples', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_scouting_samples_observed_at'))
        batch_op.drop_index(batch_op.f('ix_scouting_samples_farm_id'))
        batch_op.drop_index(batch_op.f('ix_scouting_samples_block_id'))

    op.drop_table('scouting_samples')
    # ### end Alembic commands ###
