"""p0_backfill_spine_from_farms

Re-parent every existing record onto the canonical spine, without changing any of them.

What this does, per farm:
  * one `Organization` (the farm's own, named after it)
  * one `Field` covering the whole farm, carrying its area
  * one `CropCycle` for the farm's single crop/planting/harvest triple
  * one `Operation` per existing `SprayEvent`
  * links set on sprays, scouting, samples, weather, planned sprays, input plans, blocks

Why exactly one field and one cycle. The old schema recorded ONE crop_type, ONE
planting_date and ONE expected_harvest_date per farm — so one cycle is all the data
supports. Splitting a farm into several fields, or inferring multiple seasons from spray
dates, would fabricate structure nobody recorded, which is the same error
`models.Block`'s docstring refuses to make about the free-text `field_block` column.
Every derived row is therefore tagged `data_confidence="derived"`, so a later real field
map is distinguishable from this scaffolding.

Demo/real provenance is DERIVED FROM THE FARM'S RECORDS, not read from the farm.
`farms` has no `data_source` column and never had one — provenance in this schema lives
on the record tables. So this migration reproduces what `crud.ensure_demo_real_separation`
does: it asks the same seven tables, using the same predicate as
`decision_status.is_demo_record` (`data_source = 'demo' OR data_confidence = 'simulated'`).
That guard requires one farm's records to be all demo or all real, and a real-mode Field
on a demo farm would break the invariant on the first write.

Four cases, each deliberate:

  * all records demo   -> ("demo", "simulated"). A real spine row on a demo farm would
    let simulated data be counted as traction.
  * all records real   -> ("manual_entry", "derived"). "derived" marks the row as
    scaffolding, so a later real field map is distinguishable from it.
  * records BOTH ways  -> raise. Such a farm already violates the mixing guard; a
    migration that papered over it would mint a spine row that is neither. Failing
    loudly with the farm id and the counts is the actionable behaviour.
  * no records at all  -> ("manual_entry", "derived"), and the reason is recorded in the
    derived Field's notes. This follows `crud.has_non_demo_data`'s existing stance that
    a farm with zero records cannot be proven demo. It is safe because
    `ensure_demo_real_separation` scans only the record tables — Organization, Field and
    CropCycle are not among them — so a later demo record raises no contradiction.

Currency/timezone/jurisdiction are backfilled from the SAME rule main.py's display
helper already used ("$" if country in (US, USA) else TRY), so nothing user-visible
changes — the inference simply becomes data.

Dialect-agnostic on purpose (`app/database.py` supports SQLite and PostgreSQL): no
`strftime`, no `.lastrowid`. Row ids come from `inserted_primary_key`, which resolves to
SQLite's `cursor.lastrowid` and PostgreSQL's RETURNING without this file knowing which.

Reversible: `downgrade` clears the links and removes the rows this migration created.
"""
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd4c9129576bd'
down_revision: Union[str, Sequence[str], None] = '0d3d077fde25'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DERIVED = "derived"

# The rule main.py's `_currency_symbol` already applied, made explicit.
US_COUNTRIES = ("US", "USA")

# The tables `crud.ensure_demo_real_separation` scans, as raw names. Spelled out here
# rather than imported from `app.models`, because a migration must describe the schema
# as it was AT THIS REVISION and models.py describes it as it is now.
# `tests/test_schema_migrations.py` asserts this tuple still matches
# `crud._FARM_RECORD_MODELS`, so adding a model there without updating this file is
# caught at the only moment it is cheap to fix.
FARM_RECORD_TABLES = (
    "spray_events", "scout_observations", "planned_sprays", "spray_baselines",
    "pca_policies", "blocks", "product_label_verifications",
)

# Minimal Table objects describing ONLY the columns this migration writes. The `id`
# primary key is declared so `inserted_primary_key` works on every dialect.
_meta = sa.MetaData()

_organizations = sa.Table(
    "organizations", _meta,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("name", sa.String), sa.Column("jurisdiction_code", sa.String),
    sa.Column("currency_code", sa.String), sa.Column("timezone", sa.String),
    sa.Column("notes", sa.Text), sa.Column("data_source", sa.String),
    sa.Column("data_confidence", sa.String), sa.Column("created_at", sa.DateTime),
)

_fields = sa.Table(
    "fields", _meta,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("farm_id", sa.Integer), sa.Column("organization_id", sa.Integer),
    sa.Column("name", sa.String), sa.Column("area_m2", sa.Float),
    sa.Column("display_area", sa.Float), sa.Column("display_area_unit", sa.String),
    sa.Column("notes", sa.Text), sa.Column("data_source", sa.String),
    sa.Column("data_confidence", sa.String), sa.Column("created_at", sa.DateTime),
)

_crop_cycles = sa.Table(
    "crop_cycles", _meta,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("farm_id", sa.Integer), sa.Column("field_id", sa.Integer),
    sa.Column("organization_id", sa.Integer), sa.Column("crop", sa.String),
    sa.Column("season_year", sa.Integer), sa.Column("season_label", sa.String),
    sa.Column("planting_date", sa.Date),
    sa.Column("expected_harvest_start", sa.Date),
    sa.Column("planted_area_m2", sa.Float), sa.Column("display_area", sa.Float),
    sa.Column("display_area_unit", sa.String), sa.Column("status", sa.String),
    sa.Column("currency_code", sa.String), sa.Column("notes", sa.Text),
    sa.Column("data_source", sa.String), sa.Column("data_confidence", sa.String),
    sa.Column("created_at", sa.DateTime),
)

_operations = sa.Table(
    "operations", _meta,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("farm_id", sa.Integer), sa.Column("crop_cycle_id", sa.Integer),
    sa.Column("field_id", sa.Integer), sa.Column("operation_type", sa.String),
    sa.Column("performed_on", sa.Date), sa.Column("display_area", sa.Float),
    sa.Column("display_area_unit", sa.String), sa.Column("cost_amount", sa.Float),
    sa.Column("currency_code", sa.String), sa.Column("notes", sa.Text),
    sa.Column("data_source", sa.String), sa.Column("data_confidence", sa.String),
    sa.Column("created_at", sa.DateTime),
)


# Both reads declare their result types. Without this SQLite hands back date columns as
# raw strings (a `text()` query carries no type information), and the typed INSERTs above
# would reject them — while PostgreSQL, which returns real `date` objects, would sail
# through. Declaring the types makes both backends behave the same way here.
_FARM_QUERY = sa.text(
    "SELECT id, name, country, crop_type, greenhouse_area, area_unit, "
    "       planting_date, expected_harvest_date "
    "FROM farms ORDER BY id"
).columns(
    sa.column("id", sa.Integer), sa.column("name", sa.String),
    sa.column("country", sa.String), sa.column("crop_type", sa.String),
    sa.column("greenhouse_area", sa.Float), sa.column("area_unit", sa.String),
    sa.column("planting_date", sa.Date),
    sa.column("expected_harvest_date", sa.Date),
)

_SPRAY_QUERY = sa.text(
    "SELECT id, application_date, treated_acres, treated_area_unit, cost, "
    "       data_source, data_confidence "
    "FROM spray_events WHERE farm_id = :farm ORDER BY id"
).columns(
    sa.column("id", sa.Integer), sa.column("application_date", sa.Date),
    sa.column("treated_acres", sa.Float), sa.column("treated_area_unit", sa.String),
    sa.column("cost", sa.Float), sa.column("data_source", sa.String),
    sa.column("data_confidence", sa.String),
)


class MixedProvenanceFarm(RuntimeError):
    """A farm holding both demo and real records — impossible to derive a spine row for.

    Raised rather than resolved: `crud.ensure_demo_real_separation` already forbids this
    state, so reaching it means something wrote around the guard. Picking either answer
    would mint a spine row that misrepresents half the farm.
    """


def farm_provenance(bind, farm_id):
    """(data_source, data_confidence) for rows derived from this farm's records.

    Mirrors `decision_status.is_demo_record` exactly: demo iff `data_source = 'demo'`
    OR `data_confidence = 'simulated'`. See the module docstring for the four cases.
    """
    demo = real = 0
    for table in FARM_RECORD_TABLES:
        # Table names come from the module-level constant above, never from input.
        row = bind.execute(sa.text(
            "SELECT SUM(CASE WHEN data_source = 'demo' "
            "                 OR data_confidence = 'simulated' THEN 1 ELSE 0 END) "
            "       AS demo_rows, COUNT(*) AS total_rows "
            "FROM %s WHERE farm_id = :farm" % table
        ), {"farm": farm_id}).mappings().one()
        in_table_demo = int(row["demo_rows"] or 0)
        demo += in_table_demo
        real += int(row["total_rows"] or 0) - in_table_demo

    if demo and real:
        raise MixedProvenanceFarm(
            "farm %s holds %s demo record(s) and %s real record(s); one farm's records "
            "must be all demo or all real (crud.ensure_demo_real_separation). Separate "
            "them before running this migration."
            % (farm_id, demo, real)
        )
    if demo:
        return "demo", "simulated"
    return "manual_entry", DERIVED


def _locale_for(country):
    """(currency_code, timezone, jurisdiction_code) from the country we have."""
    if (country or "").upper() in US_COUNTRIES:
        return "USD", "America/Los_Angeles", "US-CA"
    return "TRY", "Europe/Istanbul", "TR"


def _area_m2(display_area, display_unit):
    """Canonical area, or None. Never guesses which unit an unlabelled number is in."""
    if display_area is None:
        return None
    unit = (display_unit or "").strip().lower()
    if unit in ("m2", "m^2", "sqm"):
        return float(display_area)
    if unit in ("acre", "acres", "ac"):
        return float(display_area) * 4046.8564224      # exact, by definition
    if unit in ("ha", "hectare", "hectares"):
        return float(display_area) * 10_000.0
    return None


def upgrade() -> None:
    bind = op.get_bind()
    now = sa.func.current_timestamp()
    farms = bind.execute(_FARM_QUERY).mappings().all()

    for farm in farms:
        currency, tz_name, jurisdiction = _locale_for(farm["country"])
        # A derived row must not claim to be more real than the farm's own records.
        source, confidence = farm_provenance(bind, farm["id"])

        org_id = bind.execute(_organizations.insert().values(
            name=farm["name"], jurisdiction_code=jurisdiction, currency_code=currency,
            timezone=tz_name,
            notes="Created by the Phase 0 spine backfill from an existing farm.",
            data_source=source, data_confidence=confidence, created_at=now,
        )).inserted_primary_key[0]

        bind.execute(sa.text(
            "UPDATE farms SET organization_id = :org, currency_code = :cur, "
            "timezone = :tz, jurisdiction_code = :jur WHERE id = :id"
        ), {"org": org_id, "cur": currency, "tz": tz_name, "jur": jurisdiction,
            "id": farm["id"]})

        display_area = farm["greenhouse_area"]
        display_unit = farm["area_unit"]
        area_m2 = _area_m2(display_area, display_unit)

        field_notes = (
            "Derived by the Phase 0 backfill: the previous schema recorded no fields, "
            "so this one stands for the whole farm until a real field map is entered."
        )
        if confidence == DERIVED and source == "manual_entry":
            # Distinguish "this farm's records say it is real" from "this farm has no
            # records at all", which the provenance pair alone cannot express.
            field_notes += (
                " Treated as real because the farm's records say so, or because it has "
                "no records yet and a farm with no records cannot be proven demo."
            )

        field_id = bind.execute(_fields.insert().values(
            farm_id=farm["id"], organization_id=org_id, name="Whole farm",
            area_m2=area_m2, display_area=display_area, display_area_unit=display_unit,
            notes=field_notes, data_source=source, data_confidence=confidence,
            created_at=now,
        )).inserted_primary_key[0]

        season_year = None
        for candidate in (farm["planting_date"], farm["expected_harvest_date"]):
            if candidate:
                season_year = int(str(candidate)[:4])
                break
        if season_year is None:
            season_year = datetime.now(timezone.utc).year

        cycle_id = bind.execute(_crop_cycles.insert().values(
            farm_id=farm["id"], field_id=field_id, organization_id=org_id,
            crop=farm["crop_type"] or "unknown",
            season_year=season_year, season_label="%s season" % season_year,
            planting_date=farm["planting_date"],
            expected_harvest_start=farm["expected_harvest_date"],
            planted_area_m2=area_m2, display_area=display_area,
            display_area_unit=display_unit, status="growing", currency_code=currency,
            notes=("Derived by the Phase 0 backfill from the farm's single "
                   "crop_type/planting_date/expected_harvest_date."),
            data_source=source, data_confidence=confidence, created_at=now,
        )).inserted_primary_key[0]

        for table, columns in (
            ("spray_events", ("crop_cycle_id", "field_id")),
            ("scout_observations", ("crop_cycle_id", "field_id")),
            ("scouting_samples", ("crop_cycle_id",)),
            ("weather_observations", ("field_id",)),
            ("planned_sprays", ("crop_cycle_id", "field_id")),
            ("input_plans", ("crop_cycle_id",)),
            ("blocks", ("field_id",)),
        ):
            assignments = ", ".join(
                "%s = :%s" % (c, "cycle" if c == "crop_cycle_id" else "field")
                for c in columns
            )
            bind.execute(
                sa.text("UPDATE %s SET %s WHERE farm_id = :farm" % (table, assignments)),
                {"cycle": cycle_id, "field": field_id, "farm": farm["id"]},
            )

        # One Operation per spray, so "everything done to this cycle, in order" is a
        # single query. The spray keeps every regulatory column it has; the operation is
        # a spine row pointing at it, never a replacement for it.
        sprays = bind.execute(_SPRAY_QUERY, {"farm": farm["id"]}).mappings().all()

        for spray in sprays:
            op_id = bind.execute(_operations.insert().values(
                farm_id=farm["id"], crop_cycle_id=cycle_id, field_id=field_id,
                operation_type="crop_protection",
                performed_on=spray["application_date"],
                display_area=spray["treated_acres"],
                display_area_unit=spray["treated_area_unit"],
                cost_amount=spray["cost"], currency_code=currency,
                notes="Spine row for an existing spray event (Phase 0 backfill).",
                data_source=spray["data_source"] or source,
                data_confidence=spray["data_confidence"] or confidence,
                created_at=now,
            )).inserted_primary_key[0]
            bind.execute(
                sa.text("UPDATE spray_events SET operation_id = :op WHERE id = :id"),
                {"op": op_id, "id": spray["id"]},
            )


def downgrade() -> None:
    bind = op.get_bind()
    for table, columns in (
        ("spray_events", ("crop_cycle_id", "field_id", "operation_id")),
        ("scout_observations", ("crop_cycle_id", "field_id")),
        ("scouting_samples", ("crop_cycle_id",)),
        ("weather_observations", ("field_id",)),
        ("planned_sprays", ("crop_cycle_id", "field_id")),
        ("input_plans", ("crop_cycle_id",)),
        ("blocks", ("field_id",)),
    ):
        bind.execute(sa.text(
            "UPDATE %s SET %s" % (table, ", ".join("%s = NULL" % c for c in columns))
        ))
    bind.execute(sa.text("DELETE FROM operations"))
    bind.execute(sa.text("DELETE FROM crop_cycles"))
    bind.execute(sa.text("DELETE FROM fields"))
    bind.execute(sa.text(
        "UPDATE farms SET organization_id = NULL, currency_code = NULL, "
        "timezone = NULL, jurisdiction_code = NULL"
    ))
    bind.execute(sa.text("DELETE FROM organizations"))
