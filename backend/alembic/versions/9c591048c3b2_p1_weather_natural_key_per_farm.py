"""p1 weather natural key per farm

Scope the weather uniqueness constraint by farm.

`uq_weather_observation_station_hour` was `(station_id, observed_at)`, which is right
only while every station belongs to exactly one farm. It does not, and the moment
weather is ingested from a public network it stops being true: two growers subscribing
to the same CIMIS station cannot both hold the same hour, and the second insert fails
with a 409 that names a conflict the operator did not cause.

Adding `farm_id` is also the semantically correct key. `station_distance_km` is measured
to THIS farm's field, so the same station-hour is genuinely different evidence for a farm
2 km away than for one 14 km away, and `disease_risk` treats it as such.

The predicate is unchanged (`supersedes_id IS NULL`), and is emitted for BOTH dialects:
`sqlite_where` alone is silently ignored by PostgreSQL, which would build a full unique
index and make the append-only correction path impossible while appearing present.

Revision ID: 9c591048c3b2
Revises: d4c9129576bd
Create Date: 2026-08-05 13:57:40.674888

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9c591048c3b2'
down_revision: Union[str, Sequence[str], None] = 'd4c9129576bd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_NAME = "uq_weather_observation_station_hour"
PREDICATE = "supersedes_id IS NULL"


def _recreate(columns: list[str]) -> None:
    where = sa.text(PREDICATE)
    with op.batch_alter_table("weather_observations", schema=None) as batch_op:
        batch_op.drop_index(
            INDEX_NAME, sqlite_where=where, postgresql_where=where,
        )
        batch_op.create_index(
            INDEX_NAME, columns, unique=True,
            sqlite_where=where, postgresql_where=where,
        )


def upgrade() -> None:
    """Upgrade schema."""
    _recreate(["farm_id", "station_id", "observed_at"])


def downgrade() -> None:
    """Downgrade schema.

    Narrowing the key back can fail on real data: if two farms hold the same
    station-hour — which is exactly what this migration exists to allow — the old
    two-column index cannot be built. That is correct behaviour, not a bug in the
    downgrade; resolve the duplicates before going back.
    """
    _recreate(["station_id", "observed_at"])
